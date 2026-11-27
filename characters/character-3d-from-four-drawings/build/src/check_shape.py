import sys; sys.path.insert(0,'/tmp/claude-0/src')
import numpy as np, trimesh
from rast import raster
from PIL import Image
m=trimesh.load(sys.argv[1]); V=m.vertices; Fc=m.faces.astype(np.int64); N=m.vertex_normals
def view(u,dep,light):
    P=np.stack([u,V[:,1]],1).astype(np.float64)
    off=P.min(0)-10; P=P-off; W,H=int(P[:,0].max()+10),int(P[:,1].max()+10)
    sh=np.clip(N@light,0,1)*0.75+0.25
    zb,o,f=raster(P,dep.astype(np.float64),sh[:,None].astype(np.float64),Fc,W,H)
    img=np.where(f[...,None]>=0,np.repeat(o,3,2)*230,40).astype(np.uint8)
    return Image.fromarray(img)
cx=V[:,0].mean(); cz=V[:,2].mean()
L=np.array([0.3,-0.4,0.85]);
ims=[view(V[:,0],V[:,2],np.array([0.3,-0.4,0.86])), view(V[:,2],-V[:,0],np.array([-0.86,-0.4,0.3])), view(-V[:,0],-V[:,2],np.array([-0.3,-0.4,-0.86])), view(-V[:,2],V[:,0],np.array([0.86,-0.4,-0.3]))]
a=np.radians(35); u=V[:,0]*np.cos(a)+V[:,2]*np.sin(a); d=-V[:,0]*np.sin(a)+V[:,2]*np.cos(a)
ims.append(view(u,d,np.array([0.5,-0.4,0.75])))
H=max(i.size[1] for i in ims); Wt=sum(i.size[0] for i in ims)
o=Image.new('RGB',(Wt,H)); x=0
for i in ims: o.paste(i,(x,0)); x+=i.size[0]
o.save(sys.argv[2])
