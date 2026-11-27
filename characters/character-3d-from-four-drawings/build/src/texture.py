import sys; sys.path.insert(0,'/tmp/claude-0/src')
import numpy as np, trimesh, xatlas, time
from scipy import ndimage as ndi
from PIL import Image
from rast import raster
R='/mnt/project-files/character-3d/reference/'
M=np.load('/tmp/claude-0/w/masks.npz')
def load(n): return np.array(Image.open(R+n).convert('RGB')).astype(np.float32)
def vb(m):
    ys=np.where(m.any(1))[0]; return ys.min(), ys.max()
def remap_idx(m, ref):
    t,b=vb(m); T,Bb=vb(ref); idx=np.arange(1024)
    for Y in range(T,Bb+1): idx[Y]=int(round(t+(Y-T)*(b-t)/(Bb-T)))
    return idx
F0,B0,SR0,SL0=M['front'],M['back'],M['side_facing_right'],M['side_facing_left']
imF=load('front.png'); imB=load('back.png'); imSR=load('side-facing-right.png'); imSL=load('side-facing-left.png')
Bm=B0[:,::-1]; ib=remap_idx(Bm,F0); imBa=np.roll(imB[:,::-1][ib],2,1); mBa=np.roll(Bm[ib],2,1)
SLm=SL0[:,::-1]; isl=remap_idx(SLm,SR0); imSLa=np.roll(imSL[:,::-1][isl],-10,1); mSLa=np.roll(SLm[isl],-10,1)
# outside remapped range rows are copies; mask handles it
views=[ # name, image, mask, col-axis fn, depth fn, view dir (toward camera)
 ('front',imF,F0, lambda P:P[:,0], lambda P:P[:,2], np.array([0,0,1.])),
 ('back',imBa,mBa, lambda P:P[:,0], lambda P:-P[:,2], np.array([0,0,-1.])),
 ('right',imSR,SR0, lambda P:P[:,2], lambda P:-P[:,0], np.array([-1.,0,0])),
 ('left',imSLa,mSLa, lambda P:P[:,2], lambda P:P[:,0], np.array([1.,0,0])),
]
m=trimesh.load('/tmp/claude-0/w/hull_px.ply')
V=m.vertices.astype(np.float64); Fc=m.faces.astype(np.int64)
N=m.vertex_normals.copy()
if np.mean(np.sum(N*(V-V.mean(0)),1))<0: N=-N
import os
if os.path.exists('/tmp/claude-0/w/uvmesh.npz'):
    d=np.load('/tmp/claude-0/w/uvmesh.npz'); V2=d['V'];N2=d['N'];F2=d['F'];uv=d['uv']
else:
    vmap,ind,uv=xatlas.parametrize(V.astype(np.float32),Fc.astype(np.uint32))
    V2=V[vmap]; N2=N[vmap]; F2=ind.astype(np.int64)
T=2048
P=uv*T; P[:,1]=T-P[:,1]  # image rows top-down (glTF uv origin top-left handled at export)
zb,att,fid=raster(P.astype(np.float64),np.zeros(len(P)),np.hstack([V2,N2]).astype(np.float64),F2,T,T)
cov=fid>=0
pos=att[...,:3][cov]; nor=att[...,3:][cov]; nor/=np.linalg.norm(nor,axis=1,keepdims=True)+1e-9
acc=np.zeros((len(pos),3)); wsum=np.zeros(len(pos)); best=np.zeros((len(pos),3)); bestw=np.full(len(pos),-1.0)
for name,img,mask,colf,depf,d in views:
    er=ndi.binary_erosion(mask,iterations=3)
    Pv=np.stack([colf(V),V[:,1]],1); Dv=depf(V)
    zbv,_,fv=raster(Pv,Dv.astype(np.float64),np.zeros((len(V),1)),Fc,1024,1024)
    c=colf(pos); r=pos[:,1]; dp=depf(pos)
    ci=np.clip(np.round(c-0.5).astype(int),0,1023); ri=np.clip(np.round(r-0.5).astype(int),0,1023)
    vis=dp>=zbv[ri,ci]-2.5
    inside=er[ri,ci]
    nd=nor@d
    w=np.clip(nd,0,1)**6*vis*inside*(1+2*((name=='front')&(pos[:,1]<235)&(nd>0.3)))
    # bilinear sample
    x=np.clip(c-0.5,0,1022); y=np.clip(r-0.5,0,1022); x0=x.astype(int); y0=y.astype(int); fx=(x-x0)[:,None]; fy=(y-y0)[:,None]
    col=img[y0,x0]*(1-fx)*(1-fy)+img[y0,x0+1]*fx*(1-fy)+img[y0+1,x0]*(1-fx)*fy+img[y0+1,x0+1]*fx*fy
    if name in ('right','left'):
        skin=(pos[:,1]<240)&(col[:,1]>115)&(col[:,0]>150)
        w=w*(~skin)
    acc+=col*w[:,None]; wsum+=w
    fb=nd*inside+ (nd>0)*0.001
    upd=fb>bestw; best[upd]=col[upd]; bestw[upd]=fb[upd]
    print(name,'vis frac',vis.mean(),'w>0',(w>0).mean())
good=wsum>1e-4
out=acc/np.maximum(wsum,1e-9)[:,None]
from scipy.spatial import cKDTree
_,nn=cKDTree(pos[good]).query(pos[~good],workers=-1)
out[~good]=out[good][nn]
print('uncovered by weighted views',(wsum<=1e-4).mean())
tex=np.zeros((T,T,3),np.float32); tex[cov]=out
# dilate into gutters
_,(iy,ix)=ndi.distance_transform_edt(~cov,return_indices=True)
tex=tex[iy,ix]
Image.fromarray(np.clip(tex,0,255).astype(np.uint8)).save('/tmp/claude-0/w/tex.png')
np.savez('/tmp/claude-0/w/uvmesh.npz',V=V2,N=N2,F=F2,uv=uv)
