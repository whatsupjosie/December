import numpy as np
from scipy import ndimage as ndi
M=np.load('/tmp/claude-0/w/masks.npz')
F=M['front'];B=M['back'];SR=M['side_facing_right'];SL=M['side_facing_left']
def vb(m):
    ys=np.where(m.any(1))[0]; return ys.min(), ys.max()
def remap(m, ref):
    # rescale vertically so top/bottom match ref
    t,b=vb(m); T,Bb=vb(ref)
    out=np.zeros_like(m)
    for Y in range(T,Bb+1):
        y=int(round(t+(Y-T)*(b-t)/(Bb-T)))
        out[Y]=m[y]
    return out
Bm=remap(B[:,::-1],F); SLm=remap(SL[:,::-1],SR)
def best_shift(a,b,rows,clipA,clipB):
    best=None
    for s in range(-200,201):
        bb=np.roll(b,s,axis=1)
        err=0
        for y in rows:
            ra=np.where(a[y])[0]; rb=np.where(bb[y])[0]
            if len(ra)==0 or len(rb)==0: continue
            # compare both edges where neither clipped
            for ea,eb,ca,cb in ((ra.min(),rb.min(),clipA[0],clipB[0]),(ra.max(),rb.max(),clipA[1],clipB[1])):
                if abs(ea-ca)<=2 or abs(eb-cb)<=2: continue
                err+=min(abs(ea-eb),20)
        if best is None or err<best[0]: best=(err,s)
    return best
rows=range(100,960,4)
print('back shift',best_shift(F,Bm,rows,(397,626),(1023-633,1023-390)))
print('sideL shift',best_shift(SR,SLm,rows,(442,580),(1023-585,1023-436)))
from PIL import Image
def ov(a,b,name):
    img=np.zeros(a.shape+(3,),np.uint8); img[...,0]=a*255; img[...,1]=b*255
    Image.fromarray(img[40:1000,330:700]).save('/tmp/claude-0/w/'+name)
ov(F,np.roll(Bm,2,1),'ov_fb.png'); ov(SR,np.roll(SLm,-10,1),'ov_side.png')
np.savez_compressed('/tmp/claude-0/w/aligned.npz',F=F,B=np.roll(Bm,2,1),SR=SR,SL=np.roll(SLm,-10,1))
