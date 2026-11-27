import sys; sys.path.insert(0,'/tmp/claude-0/src')
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rast import raster
d=np.load('/tmp/claude-0/w/uvmesh.npz'); V=d['V'];N=d['N'];F=d['F'];uv=d['uv']
tex=np.array(Image.open(sys.argv[1] if len(sys.argv)>1 else '/tmp/claude-0/w/tex.png')).astype(np.float32); T=tex.shape[0]
BG=np.array([209,215,225],np.float32)
def render(col,dep,light,W=1024,H=1024,flip=False):
    P=np.stack([col,V[:,1]],1).astype(np.float64)
    sh=0.82+0.18*np.clip(N@light,0,1)
    zb,o,f=raster(P,dep.astype(np.float64),np.hstack([uv,sh[:,None]]).astype(np.float64),F,W,H)
    u=np.clip(o[...,0]*T,0,T-1).astype(int); v=np.clip((1-o[...,1])*T,0,T-1).astype(int)
    c=tex[v,u]*o[...,2:3]
    img=np.where((f>=0)[...,None],c,BG)
    if flip: img=img[:,::-1]
    return Image.fromarray(np.clip(img,0,255).astype(np.uint8))
r={}
r['front']=render(V[:,0],V[:,2],np.array([0.3,-0.3,0.9]))
r['back']=render(V[:,0],-V[:,2],np.array([0.3,-0.3,-0.9]),flip=True)
r['right']=render(V[:,2],-V[:,0],np.array([-0.9,-0.3,0.3]))
r['left']=render(V[:,2],V[:,0],np.array([0.9,-0.3,0.3]),flip=True)
cx=(V[:,0].min()+V[:,0].max())/2; cz=(V[:,2].min()+V[:,2].max())/2
for nm,a in (('three-quarter-front',35),('three-quarter-back',215)):
    t=np.radians(a); x=V[:,0]-cx; z=V[:,2]-cz
    u=x*np.cos(t)-z*np.sin(t)+512; dp=x*np.sin(t)+z*np.cos(t)
    r[nm]=render(u,dp,np.array([0.4,-0.3,0.85]))
out=sys.argv[2] if len(sys.argv)>2 else '/tmp/claude-0/w/r'
for k,im in r.items(): im.save(f'{out}-{k}.png')
