import numpy as np, trimesh
from PIL import Image
d=np.load('/tmp/claude-0/w/uvmesh.npz'); V=d['V'];F=d['F'];uv=d['uv']
ymin,ymax=V[:,1].min(),V[:,1].max(); hpx=ymax-ymin
s=1.727/hpx
cx=(V[:,0].min()+V[:,0].max())/2; cz=(V[:,2].min()+V[:,2].max())/2
Vm=np.stack([(V[:,0]-cx)*s,(ymax-V[:,1])*s,(V[:,2]-cz)*s],1)
Fm=F[:,::-1]  # y flip mirrors, so reverse winding
tex=Image.open('/tmp/claude-0/w/tex.png')
mat=trimesh.visual.material.PBRMaterial(name='character',baseColorTexture=tex,metallicFactor=0.0,roughnessFactor=0.85)
m=trimesh.Trimesh(Vm,Fm,visual=trimesh.visual.TextureVisuals(uv=uv,material=mat),process=False)
out='/mnt/project-files/character-3d/character-unrigged-v1.glb'
m.export(out)
r=trimesh.load(out,force='mesh')
b=r.bounds; print('bounds m',b.round(3),'height',round(b[1,1]-b[0,1],3),'tris',len(r.faces))
n=r.face_normals; c=r.triangles_center
print('outward normals frac',np.mean(np.sum(n*(c-c.mean(0)),1)>0))
# facing check: nose region (top ~10%) should be at +Z side; front texture has face, check mean z of skin texels unnecessary
print('px per m',1/s, 'scale', s)
