import numpy as np, trimesh, fast_simplification
from scipy import ndimage as ndi
from skimage import measure
A=np.load('/tmp/claude-0/w/aligned.npz'); F=A['F'];B=A['B'];SR=A['SR'];SL=A['SL']
S=SR|SL
sm=lambda m: ndi.gaussian_filter(m.astype(np.float32),(4.0,1.2))>0.5
F=sm(F); S=sm(S)
# chest/front clip repair: where union front edge sits on right-view clip col (>=578) for a run of rows, bulge outward
fe=np.array([np.where(S[y])[0].max() if S[y].any() else -1 for y in range(1024)])
clip=(fe>=578)
lab,n=ndi.label(clip)
S2=S.copy()
for i in range(1,n+1):
    ys=np.where(lab==i)[0]
    if len(ys)<6: continue
    t=(ys-ys[0])/(max(1,ys[-1]-ys[0]))
    bump=(10*np.sin(np.pi*t)).astype(int)
    for y,bmp in zip(ys,bump):
        S2[y,fe[y]:fe[y]+bmp+1]=True
print('clip bulges',[(int(np.where(lab==i)[0][0]),int(np.where(lab==i)[0][-1])) for i in range(1,n+1)])
S=S2
X0,X1=370,660; Z0,Z1=400,640; Y0,Y1=50,990
nx,nz,ny=X1-X0,Z1-Z0,Y1-Y0
occ=np.zeros((ny,nx,nz),np.float32)
xs=np.arange(X0,X1)[:,None]; zs=np.arange(Z0,Z1)[None,:]
def runs(row):
    r=[];s=None
    for x,c in enumerate(row):
        if c and s is None:s=x
        if not c and s is not None: r.append((s,x-1)); s=None
    if s is not None: r.append((s,len(row)-1))
    return r
def supell(a,b,c,d,p):
    cx=(a+b)/2; rx=max((b-a)/2,0.5); cz=(c+d)/2; rz=max((d-c)/2,0.5)
    return (np.abs((xs-cx)/rx)**p+np.abs((zs-cz)/rz)**p)<=1.0
# arm zone
widths=np.array([F[y].sum() for y in range(1024)])
YS=None
for y in range(150,400):
    rr=runs(F[y])
    if rr and rr[-1][1]-rr[0][0]>170: YS=y;break
YH=592; HEM=440
print('shoulder row',YS)
CROTCH=None
for y in range(450,800):
    if len([r for r in runs(F[y]) if r[1]-r[0]>=20])>=2 and runs(F[y])[0][0]>415: CROTCH=y; break
CROTCH=CROTCH or 560
print('crotch',CROTCH)
def wa(y):
    if y<HEM: return np.interp(y,[YS,YS+30,HEM],[30,46,44])
    return np.interp(y,[HEM,HEM+15,500,560,YH],[44,30,27,20,4])
for y in range(Y0,Y1):
    fr=F[y]; sr=S[y]
    if not fr.any() or not sr.any(): continue
    srun=np.where(sr)[0]; c,d=srun.min(),srun.max()
    sl=np.zeros((nx,nz),bool)
    rr=runs(fr)
    if YS is not None and YS<=y<=YH:
        L=rr[0][0]; R=rr[-1][1]; w=wa(y)
        zc=(c+d)/2; r=w/2
        for cx in (L+w/2, R-w/2):
            sl|=((xs-cx)**2/(r*r)+(zs-zc)**2/(r*r*1.0))<=1
        cut=np.zeros(1024,bool); cut[int(L+w*0.75):int(R-w*0.75)+1]=True
        for a,b in runs(fr&cut):
            if b-a<6: continue
            p=float(np.interp(y,[HEM,HEM+80],[2.6,2.3]))
            sl|=supell(a,b,c,d,p)
    else:
        legs=[(a,b) for a,b in rr if b-a>=3]
        p=2.0 if (YS is None or y<YS) else 2.3
        if y>YH and len(legs)>=2:
            t=float(np.clip((y-CROTCH)/70.0,0,1))
            hip=supell(legs[0][0],legs[-1][1],c,d,2.6)
            lg=np.zeros_like(hip)
            for a,b in legs: lg|=supell(a,b,c,d,p)
            # shrink legs' depth toward hip profile near the crotch
            cz=(c+d)/2; rz=(d-c)/2
            for a,b in legs:
                cx=(a+b)/2; rx=max((b-a)/2,0.5)
                rzl=rz*(1-0.25*(1-t))
                lg2=(np.abs((xs-cx)/rx)**p+np.abs((zs-cz)/rzl)**p)<=1
                hip_t=hip if t<1 else np.zeros_like(hip)
                sl|=(lg2&(hip|(t>0.999)))|(lg2 if t>=1 else False)
        else:
            for a,b in legs:
                sl|=supell(a,b,c,d,p)
    sl&=fr[X0:X1][:,None]; sl&=sr[Z0:Z1][None,:]
    occ[y-Y0]=sl
occ=ndi.gaussian_filter(occ,(5.5,1.6,1.6))
ZF=0.42
occs=ndi.zoom(occ,ZF,order=1)
verts,faces,norm,_=measure.marching_cubes(occs,0.5)
verts=verts/ZF
V=np.stack([verts[:,1]+X0,verts[:,0]+Y0,verts[:,2]+Z0],1)
m=trimesh.Trimesh(V,faces,process=True)
print('mc',len(m.vertices),len(m.faces),'maxedge',m.edges_unique_length.max())
# keep largest component
comps=m.split(only_watertight=False); m=max(comps,key=lambda c:len(c.faces))
print('final',len(m.vertices),len(m.faces),'watertight',m.is_watertight)
m.export('/tmp/claude-0/w/hull_px.ply')
