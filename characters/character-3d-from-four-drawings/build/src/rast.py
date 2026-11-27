import numpy as np
from numba import njit
@njit(cache=True)
def raster(P, D, Att, Fc, W, H):
    # P: (N,2) pixel coords (x right, y down), D: (N,) depth larger=closer, Att: (N,k)
    k=Att.shape[1]
    zb=np.full((H,W),-1e9); out=np.zeros((H,W,k)); fid=np.full((H,W),-1)
    for t in range(Fc.shape[0]):
        i0,i1,i2=Fc[t,0],Fc[t,1],Fc[t,2]
        x0,y0=P[i0,0],P[i0,1]; x1,y1=P[i1,0],P[i1,1]; x2,y2=P[i2,0],P[i2,1]
        area=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
        if abs(area)<1e-12: continue
        xmin=max(int(np.floor(min(x0,x1,x2))),0); xmax=min(int(np.ceil(max(x0,x1,x2))),W-1)
        ymin=max(int(np.floor(min(y0,y1,y2))),0); ymax=min(int(np.ceil(max(y0,y1,y2))),H-1)
        for py in range(ymin,ymax+1):
            for px in range(xmin,xmax+1):
                sx=px+0.5; sy=py+0.5
                w0=((x1-sx)*(y2-sy)-(x2-sx)*(y1-sy))/area
                w1=((x2-sx)*(y0-sy)-(x0-sx)*(y2-sy))/area
                w2=1-w0-w1
                if w0<-1e-6 or w1<-1e-6 or w2<-1e-6: continue
                z=w0*D[i0]+w1*D[i1]+w2*D[i2]
                if z>zb[py,px]:
                    zb[py,px]=z; fid[py,px]=t
                    for c in range(k):
                        out[py,px,c]=w0*Att[i0,c]+w1*Att[i1,c]+w2*Att[i2,c]
    return zb,out,fid
