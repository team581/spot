"""Build Spot's editable GUI reference assets (revision 3)."""
from pathlib import Path
import json,html,re,math
from restyle import icon_svg,PATHS
P=Path(__file__).parent
C=dict(bg='#F4F5F7',surface='#FFFFFF',ink='#202226',muted='#66696E',line='#DEE3E8',accent='#591616',accentLight='#F6EEEE',green='#226844',greenLight='#EAF4EE',amber='#825A16',amberLight='#FFF4DF',blue='#255A86',blueLight='#EAF2F9',video='#26323D')
PATHS['Network']='<path d="M8 3v5m8-5v5M5 8h14v6H5Zm7 6v7m-5 0h10"/>'
PATHS['System']=PATHS['Network & System']
B=[];S=[]
def r(x,y,w,h,c='surface',radius=0,stroke=None,name='Surface'):
 if w<=0 or h<=0:return
 S.append(dict(type='rect',x=x,y=y,w=w,h=h,fill=C.get(c,c),r=radius,stroke=C.get(stroke,stroke),name=name))
def t(x,y,v,size=14,c='ink',weight=400,w=None):
 S.append(dict(type='text',x=x,y=y,w=w or max(30,len(v)*size*.58),h=size*1.45,text=v,size=size,fill=C.get(c,c),weight=weight,name=v))
def svg(x,y,w,h,raw,name):S.append(dict(type='svg',x=x,y=y,w=w,h=h,svg=raw,name=name))
def btn(x,y,label,w=130,primary=False,disabled=False):
 r(x,y,w,34,'line' if disabled else 'accent' if primary else 'surface',6,None if primary else 'line',label+' button');t(x+12,y+7,label,14,'muted' if disabled else '#FFFFFF' if primary else 'ink',600,w-24)
def panel(x,y,w,h,title=None):
 r(x,y,w,h,'surface',8,'line');
 if title:t(x+16,y+14,title,18,weight=600,w=w-32)
def field(x,y,label,value,w=270):
 t(x,y,label,13,'muted',w=w);r(x,y+23,w,34,'surface',5,'line');t(x+10,y+29,value,14,w=w-20)
def metric(x,y,v,label,w=150):t(x,y,v,26,weight=600,w=w);t(x,y+34,label,12,'muted',w=w)
def history_icons(x,y,can_undo=False,can_redo=False):
 for dx,name,enabled in [(0,'Undo',can_undo),(32,'Redo',can_redo)]:
  d='M9 5 4 10l5 5M4 10h9a6 6 0 0 1 6 6' if name=='Undo' else 'm15 5 5 5-5 5m5-5h-9a6 6 0 0 0-6 6'
  color=C['muted'] if enabled else '#BFC5CC'
  raw=f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="{d}"/></svg>'
  svg(x+dx,y,20,20,raw,'History / '+name+(' / enabled' if enabled else ' / disabled'))
def number_field(x,y,label,value,unit,w=248,focused=False):
 t(x,y+10,label,14,weight=600,w=30);r(x+34,y,w-34,42,'surface',6,'accent' if focused else 'line','Number input / '+label)
 t(x+48,y+9,value,18,weight=600,w=w-130);t(x+w-68,y+11,unit,14,'muted',w=28)
 raw='<svg xmlns="http://www.w3.org/2000/svg" width="20" height="24" viewBox="0 0 20 24" fill="none" stroke="'+C['muted']+'" stroke-width="1.4" stroke-linecap="round"><path d="m5 8 4-4 4 4m-8 8 4 4 4-4"/></svg>'
 svg(x+w-28,y+9,18,24,raw,'Number stepper / '+label)
 if focused:r(x+48+len(value)*9,y+11,1,20,'accent',name='Input caret / end')
def theme_control(compact=False):
 x=18 if compact else 24;y=844 if compact else 754
 r(x,y,34,34,'bg',8,name='Theme / Auto / trigger')
 raw='<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="'+C['muted']+'" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M12 17v4m-4 0h8"/></svg>'
 svg(x+7,y+7,20,20,raw,'Theme / Auto / monitor icon')
def check(x,y,label,on=True,w=200):
 r(x,y,16,16,'accent' if on else 'surface',3,None if on else 'line');
 if on:t(x+3,y-2,'✓',13,'#FFFFFF',600,15)
 t(x+25,y-2,label,14,w=w-25)
def slider(x,y,label,value,left,right,w=248,portion=.48):
 t(x,y,label,14,weight=600,w=w-78);r(x+w-74,y-3,74,28,'bg',5,'line');t(x+w-65,y+1,value,13,weight=600,w=66)
 r(x,y+39,w,4,'line',2);r(x,y+39,w*portion,4,'accent',2);r(x+w*portion-7,y+33,16,16,'surface',8,'accent');t(x,y+58,left,11,'muted',w=70);t(x+w-62,y+58,right,11,'muted',w=75)
def shell(name,title,active='Overview',compact=False):
 global S
 S=[];B.append(dict(name=name,w=1024 if compact else 1440,h=900,shapes=S));W=B[-1]['w'];side=72 if compact else 216
 r(0,0,W,900,'bg');r(0,0,side,900,'surface');r(side-1,0,1,900,'line');svg(17 if compact else 20,22,40,40,(P/'blazing-bulldogs.svg').read_text(),'Blazing Bulldogs logo')
 if not compact:t(72,29,'Spot',24,weight=600,w=130)
 nav=[('Overview',105),('Cameras',153),('front-left',200),('front-right',237),('rear-left',274),('rear-right',311),('USB-A5',348),('Calibration',406),('Network',454),('System',502),('Docs',550)]
 if compact:nav=[('Overview',105),('Cameras',165),('Calibration',225),('Network',285),('System',345),('Docs',405)]
 for label,y in nav:
  chosen=label==active or compact and active=='front-left' and label=='Cameras';main=label in PATHS
  if chosen:r(12,y-7,48 if compact else 192,36,'accent',7)
  color='#FFFFFF' if chosen else C['muted']
  if main:svg(25 if compact else 24,y,20,20,icon_svg(label,color),'Icon / '+label)
  if not compact:
   t(52,y+1,label,14,color,600 if chosen else 400,146)
   if label in ['USB-A5','rear-right']:t(184,y+1,'⚠',13,'amber',600,20)
 if not compact:
  r(24,805,168,1,'line');t(24,827,'Updated Oct 4, 18:42',11,'muted',w=180);t(24,848,'abc1234',11,'muted',w=180)
 theme_control(compact)
 t(96 if compact else 248,30,title,28,weight=600,w=W-side-64)
 return S

def feed(x,y,w,h,tags=True):
 r(x,y,w,h,'video',6,name='Camera feed');r(x+12,y+h*.58,w-24,h*.36,'#3D4A55',3)
 for i in range(4):r(x+18+i*(w-30)/4,y+h*.77,(w-32)/4,1,'#64727D')
 r(x+w*.18,y+h*.34,w*.64,4,'#72808B');r(x+w*.18,y+h*.34,4,h*.40,'#72808B');r(x+w*.82-4,y+h*.34,4,h*.40,'#72808B')
 if tags:
  for p,id in [(.35,'18'),(.62,'21')]:
   q=min(w*.09,h*.21);xx=x+w*p;yy=y+h*.37;r(xx-3,yy-3,q+6,q+6,'#71C7A1',2);r(xx,yy,q,q,'#FFFFFF');r(xx+4,yy+4,q-8,q-8,'#17212D');r(xx+q*.32,yy+q*.32,q*.36,q*.36,'#FFFFFF');t(xx-2,yy-21,'#'+id,12,'#A5E1C3',600,50)

def viewer(x,y,w,h,fieldview=False):
 r(x,y,w,h,'#F8F9FA',6,'line', '3D / field' if fieldview else '3D / robot geometry')
 ca,sa,ce,se=math.cos(-1.05),math.sin(-1.05),math.cos(.72),math.sin(.72);scale=min(w/3.2,h/2.6)
 def pr(p):
  a,b,c=p;return (w*.48+(-sa*a+ca*b)*scale,h*.68-(-se*ca*a-se*sa*b+ce*c)*scale)
 paths=[]
 def path(points,col,width=1.2,close=False):
  q=[pr(v) for v in points];d='M'+' L'.join(f'{a:.2f} {b:.2f}' for a,b in q)+(' Z' if close else '');paths.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{width}" stroke-linejoin="round"/>')
 def box(a,b,c,l,ww,hh,col):
  base=[(a,b,c),(a+l,b,c),(a+l,b+ww,c),(a,b+ww,c)];top=[(aa,bb,c+hh) for aa,bb,cc in base];path(base,col,2,True);path(top,col,2,True)
  for p,q in zip(base,top):path([p,q],col,1.6)
 def arrow(a,b,col):
  path([a,b],col,2.6);p,q=pr(a),pr(b);ang=math.atan2(q[1]-p[1],q[0]-p[0]);head=[(q[0]-12*math.cos(ang-.45),q[1]-12*math.sin(ang-.45)),q,(q[0]-12*math.cos(ang+.45),q[1]-12*math.sin(ang+.45))];paths.append('<path d="M'+' L'.join(f'{aa:.2f} {bb:.2f}' for aa,bb in head)+'" fill="none" stroke="'+col+'" stroke-width="2.6"/>')
 for j in [-.9,-.6,-.3,0,.3,.6,.9]:path([(-.9,j,0),(.9,j,0)],'#E1E5E9');path([(j,-.9,0),(j,.9,0)],'#E1E5E9')
 box(-.36,-.32,.10,.72,.64,.18,'#66696E')
 for a in [-.28,.15]:
  for b in [-.38,.30]:box(a,b,.02,.13,.08,.19,'#949BA4')
 arrow((0,0,.31),(.84,0,.31),C['accent']);fx,fy=pr((.86,0,.31));t(x+fx-16,y+fy-23,'Front',12,'accent',600,70)
 box(.12,.15,.36,.16,.12,.12,C['blue']);arrow((.28,.21,.42),(.92,.21,.30),C['blue']);cx,cy=pr((.96,.21,.30));t(x+cx-15,y+cy+7,'Lens',12,'blue',600,70)
 if fieldview:
  for pt,id in [((-.75,.65,.35),'18'),((.55,.78,.35),'21')]:box(*pt,.12,.03,.12,C['green']);aa,bb=pr(pt);t(x+aa,y+bb-21,'#'+id,11,'green',600,45)
 svg(x,y,w,h,f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'+''.join(paths)+'</svg>','Wireframe / robot and lens arrows')
 btn(x+w-120,y+12,'Reset view',108)

shell('01 Overview','Overview')
for x,y,label,missing in [(248,96,'front-left',False),(844,96,'front-right',False),(248,488,'rear-left',False),(844,488,'rear-right',True)]:
 panel(x,y,556,364);t(x+16,y+14,label,19,weight=600,w=300);t(x+432,y+17,'✓ calibrated',12,'green',w=118)
 if missing:
  r(x+12,y+48,532,225,'#EBEEF1',6);t(x+30,y+125,'Disconnected',22,weight=600,w=450);t(x+30,y+159,'Last frame 2.4 s ago',14,'muted',w=450)
 else:feed(x+12,y+48,532,225)
 t(x+16,y+296,'— FPS' if missing else '18 FPS',23,weight=600,w=170);t(x+196,y+296,'— tags' if missing else '2 tags',23,weight=600,w=150);t(x+360,y+296,'2.4 s' if missing else '48 ms',23,weight=600,w=170)

shell('02 Camera detail','front-left','front-left');btn(248,80,'Camera',104,True);btn(364,80,'Geometry',120);t(1216,39,'✓ calibrated',12,'green',w=172)
panel(248,137,292,701,'Config');history_icons(456,153,True,False)
slider(268,247,'Exposure','5.0 ms','0.1','20 ms',248,.26);slider(268,343,'Gain','6 dB','0','24 dB',248,.25);slider(268,439,'Brightness','128','0','255',248,.50)
field(268,539,'Resolution','640 × 480  ▾',248);field(268,607,'Capture rate','30 fps  ▾',248);t(268,678,'Applied 5.0 ms · 6 dB · 128',12,'green',w=250);btn(268,717,'Reset to code defaults',248);t(268,789,'Advanced  ›',13,'muted',w=248)
feed(560,137,840,448);t(576,153,'',1,w=1) if False else None
check(560,602,'Show detection outlines',True,238);btn(820,596,'Pause image',132);t(996,604,'Frame 1842 · 48 ms · 640 × 480',13,'muted',w=390)
panel(560,648,394,190,'Detections');t(576,693,'ID         Range           Error           Used',12,'muted',w=361);t(576,723,'18         2.8 m            0.42 px         ✓',15,w=361);t(576,751,'21         3.1 m            0.39 px         ✓',15,w=361);t(576,797,'Robot: accepted · fusion off',13,'green',w=361)
viewer(978,648,422,190,True)

shell('03 Camera name','USB-A5','USB-A5');feed(248,96,756,492,False);panel(1028,96,372,280,'Camera name');t(1044,152,'⚠ Not configured in code',14,'amber',600,w=336);field(1044,192,'Name','rear-right  ▾',336);btn(1044,271,'Rename',336,True);t(1044,325,'USB-A5 · port 1-3.1',12,'muted',w=336)
t(248,618,'640 × 480 · 30 fps',13,'muted',w=600);t(1028,404,'⚠ Not calibrated',14,'amber',w=350)

shell('04 Calibration capture','Calibration','Calibration');btn(248,80,'Capture',100,True);btn(360,80,'Results / history',158);btn(1130,80,'Pause all',116);btn(1258,80,'Reset session',142)
for x,y,label,n,cov in [(248,138,'front-left',24,68),(684,138,'front-right',18,52),(248,462,'rear-left',16,48),(684,462,'rear-right',0,0)]:
 panel(x,y,414,300);check(x+14,y+15,label,n>0,310)
 if n:feed(x+12,y+47,390,161,False)
 else:r(x+12,y+47,390,161,'#EBEEF1',6);t(x+36,y+113,'Disconnected',17,'muted',w=320)
 if n:
  for row in range(4):
   for col in range(10):r(x+32+col*31,y+73+row*28,3,3,'#6DE0BA' if (row+col)%3 else '#F1BD62',2)
 r(x+14,y+220,386,4,'line',2);r(x+14,y+220,386*cov/100,4,'accent',2);t(x+14,y+234,f'{n} views · {cov}% coverage'+(' · board found' if n else ''),12,'muted',w=386)
 btn(x+14,y+263,'Pause' if n else 'Start',102,disabled=not n);btn(x+128,y+263,'Capture',114,disabled=not n);btn(x+254,y+263,'Calibrate',146,primary=True,disabled=not n)
panel(1120,138,280,624,'Board');field(1136,187,'Dictionary','DICT_4X4_250 ▾',248);field(1136,254,'Squares','15 × 15',248);field(1136,321,'Square size','30 mm',248);field(1136,388,'Marker size','22 mm',248);field(1136,455,'Model','Plumb bob · 5 ▾',248);field(1136,522,'Minimum views','15',248);btn(1136,599,'Start automatic capture',248,True);t(1136,664,'Fit / validation',14,weight=600,w=248);btn(1136,699,'Validation capture',248)

shell('05 Calibration results and history','Calibration','Calibration');btn(248,80,'Capture',100);btn(360,80,'Results / history',158,True)
panel(248,138,1152,285,'Results');t(268,188,'Camera                  Fit RMS         Validation RMS        Views          Result',13,'muted',w=1070)
for y,name,fit,val,n,passed in [(226,'front-left','0.31 px','0.46 px','24 / 12',True),(276,'front-right','0.35 px','1.92 px','18 / 10',False)]:
 check(268,y,name,True,205);t(524,y,fit,15,w=135);t(704,y,val,15,w=190);t(932,y,n,15,w=140);t(1120,y,'✓ Pass' if passed else '⚠ Retry',15,'green' if passed else 'amber',600,150)
t(268,331,'front-right · validation failed',13,'amber',w=640);btn(268,372,'Apply selected',164,True,True);btn(444,372,'Select passing',162);btn(618,372,'Retry capture',150)
panel(248,447,1152,228,'History');t(268,496,'Generation          Cameras                         Mode                  Saved                   Status',13,'muted',w=1090)
t(268,534,'gen-07                 front-left, front-right         640 × 480           Oct 4, 18:12        ✓ Active',15,w=1100);t(268,579,'gen-06                 front-left, front-right         640 × 480           Sep 30, 16:20',15,w=900);btn(1188,570,'Restore',184)
t(248,707,'Apply status: gen-07 active',13,'muted',w=600)

shell('06 Network','Network','Network');panel(248,96,552,355,'Connection');field(268,149,'Robot endpoint','10.5.81.2',512);field(268,222,'NetworkTables server','roboRIO · team 581',512);field(268,295,'Connection mode','Automatic discovery  ▾',512);btn(268,387,'Reset to code defaults',222)
panel(824,96,576,355,'Link');t(844,156,'Ethernet              Connected',16,w=530);t(844,199,'NetworkTables     Connected',16,w=530);t(844,242,'Jetson IP             192.168.69.170',16,w=530);t(844,285,'Clock sync           Valid · 0.2 s ago',16,w=530);t(844,328,'Reconnects          2',16,w=530)

shell('07 Docs','Docs','Docs');r(248,85,1152,42,'surface',6,'line');t(266,96,'⌕ Search docs',14,'muted',w=1090)
panel(248,147,256,706)
for y,title in [(164,'GETTING STARTED'),(398,'GUIDES'),(594,'REFERENCE')]:t(264,y,title,11,'muted',600,224)
items=[(204,'1. Connect to Spot'),(244,'2. Name cameras'),(284,'3. Set camera geometry'),(324,'4. Calibrate'),(364,'5. Verify detections'),(438,'Camera tuning'),(478,'Replace a camera'),(518,'Network recovery'),(558,'Deployment / rollback'),(634,'API / Java integration'),(674,'Coordinate frames'),(714,'Calibration metrics'),(754,'Faults / logs')]
for y,label in items:
 if y==244:r(260,y-8,232,34,'accentLight',4)
 t(272,y,label,14,'accent' if y==244 else 'ink',600 if y==244 else 400,216)
panel(524,147,678,706);t(552,169,'2. Name cameras',27,weight=600,w=614)
t(552,229,'Find the camera',19,weight=600,w=614);t(552,266,'1. Plug the camera into the powered USB hub.',16,w=614);t(552,297,'2. Open the camera marked ⚠ in the sidebar.',16,w=614)
t(552,365,'Choose its name',19,weight=600,w=614);t(552,402,'3. Pick its name from the names configured in robot code.',16,w=614);t(552,438,'Example: choose rear-right for the rear-right camera.',14,'muted',w=614)
t(552,507,'Rename and calibrate',19,weight=600,w=614);t(552,544,'4. Click Rename. The sidebar shows the new name.',16,w=614);t(552,580,'5. Open Calibration if the camera still has a warning.',14,'muted',w=614)
t(552,650,'Next: Set camera geometry',17,'accent',600,w=614);btn(552,737,'Next  →',145)
t(1224,168,'ON THIS PAGE',11,'muted',600,174);t(1224,207,'Find the camera',13,w=174);t(1224,243,'Choose its name',13,w=174);t(1224,279,'Rename and calibrate',13,w=174)

shell('08 Compact camera','front-left','front-left',True);btn(96,80,'Camera',100,True);btn(208,80,'Geometry',116)
panel(96,138,246,661,'Config');history_icons(262,154,False,False);slider(112,249,'Exposure','5 ms','0.1','20 ms',212,.25);slider(112,346,'Gain','6 dB','0','24 dB',212,.25);slider(112,443,'Brightness','128','0','255',212,.50);btn(112,561,'Reset to code defaults',212);t(112,624,'Robot enabled · locked',13,'amber',w=212)
feed(362,138,638,362);check(362,516,'Detection outlines',True,204);btn(586,510,'Pause image',138);t(747,518,'48 ms · 2 tags',13,'muted',w=245);viewer(362,563,638,236,True)

shell('09 Camera geometry','front-left','front-left');btn(248,80,'Camera',104);btn(364,80,'Geometry',120,True)
panel(248,137,292,485,'Geometry');history_icons(456,153,False,False)
for y,label,val,unit in [(202,'X','0.24','m'),(264,'Y','0.18','m'),(326,'Z','0.42','m'),(388,'Yaw','0','°'),(450,'Pitch','10','°'),(512,'Roll','0','°')]:number_field(268,y,label,val,unit,248,label=='X')
btn(268,576,'Reset to code defaults',248);viewer(560,137,840,603)
t(560,769,'X 0.24 m     Y 0.18 m     Z 0.42 m     Yaw 0°     Pitch 10°     Roll 0°',16,w=838)

shell('10 System','System','System');panel(248,96,1152,109)
for x,v,label in [(268,'42%','CPU'),(500,'36%','GPU'),(732,'58 °C','Temperature'),(964,'1.8 / 8 GB','Memory'),(1196,'12 min','Uptime')]:metric(x,114,v,label,196)
panel(248,229,557,259,'Camera pipelines');t(268,279,'Camera           Capture / detect       Drop        Frame age',12,'muted',w=514)
for y,cam,rate,drop,age in [(319,'front-left','30 / 18 fps','0.3%','48 ms'),(356,'front-right','30 / 17 fps','0.2%','52 ms'),(393,'rear-left','30 / 18 fps','0.3%','45 ms'),(430,'rear-right','—','—','2.4 s')]:t(268,y,f'{cam:<17}{rate:<22}{drop:<13}{age}',13,'amber' if cam=='rear-right' else 'ink',w=514)
panel(829,229,571,259,'Software');t(849,281,'Running          beta.01 · abc1234',15,w=531);t(849,321,'Deployed        Oct 4, 18:42',15,w=531);t(849,361,'Started           Oct 7, 15:08',15,w=531);t(849,401,'Detector         CUDA · a7e91c',15,w=531);t(849,441,'Startup           21.4 s · network wait 4.2 s',13,'muted',w=531)
panel(248,512,1152,220,'Faults / USB');t(268,561,'⚠ rear-right disconnected · USB 1-2.4',16,'amber',600,w=1090);t(268,605,'Hub 1-2    →    1-2.1 front-left    /    1-2.2 front-right    /    1-2.3 rear-left',14,w=1090);t(268,650,'Transport loss 0.3%      Clock valid      Reconnects 2',14,'muted',w=1090)
btn(248,766,'Export support bundle',216);btn(476,766,'Record debug · 60 s',208)

# Reference state board, outside the app navigation.
S=[];B.append(dict(name='11 States',w=1440,h=900,shapes=S));r(0,0,1440,900,'bg');t(40,30,'UI states',28,weight=600,w=1320)
for x,y,title,body,tone in [(40,98,'Live Config','Exposure 5.0 ms · applied 5.0 ms','green'),(736,98,'Control rejected','Exposure 0.1 ms · minimum 0.5 ms','amber'),(40,278,'No robot','Robot decision — · cached geometry','muted'),(736,278,'Stale image','Last frame 1.2 s ago · overlays hidden','amber'),(40,458,'Calibration apply','Awaiting acknowledgement · gen-07 active','blue'),(736,458,'Other browser changed config','Read current values before undoing','amber'),(40,638,'Uncalibrated camera','⚠ front-left · calibration required','amber'),(736,638,'Time unavailable','beta.01 · abc1234 · uptime 12 min','muted')]:panel(x,y,664,146,title);t(x+16,y+62,body,15,tone,w=626)

from theme import dark_boards, theme_menus, DARK
D=dark_boards(B)
M=theme_menus(B,D)
(P/"theme-boards.json").write_text(json.dumps(M,ensure_ascii=False,indent=2))
(P/'dark-boards.json').write_text(json.dumps(D,ensure_ascii=False,indent=2))
(P/'dark-tokens.json').write_text(json.dumps(DARK,indent=2))

# Portable SVG + edit manifest. Native Penpot imports use the same shape primitives.
for b in B+D+M:
 out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{b["w"]}" height="{b["h"]}" viewBox="0 0 {b["w"]} {b["h"]}">']
 for a in b['shapes']:
  if a['type']=='rect':out.append(f'<rect x="{a["x"]}" y="{a["y"]}" width="{a["w"]}" height="{a["h"]}" rx="{a["r"]}" fill="{a["fill"]}"'+(f' stroke="{a["stroke"]}"' if a.get('stroke') else '')+'/>')
  elif a['type']=='svg':
   raw=a['svg'];raw=re.sub(r'width="[^"]+"',f'width="{a["w"]}"',raw,count=1);raw=re.sub(r'height="[^"]+"',f'height="{a["h"]}"',raw,count=1);out.append(raw.replace('<svg ',f'<svg x="{a["x"]}" y="{a["y"]}" ',1))
  else:out.append(f'<text x="{a["x"]}" y="{a["y"]+a["size"]}" font-family="Source Sans Pro, Arial, sans-serif" font-size="{a["size"]}" font-weight="{a["weight"]}" fill="{a["fill"]}">{html.escape(a["text"])}</text>')
 out.append('</svg>');(P/(b['name'].replace(' / ','-').replace(' ','-').lower()+'.svg')).write_text('\n'.join(out))
(P/'boards.json').write_text(json.dumps(B,ensure_ascii=False,indent=2));(P/'tokens.json').write_text(json.dumps(C,indent=2));print(f'{len(B+D+M)} light/dark/theme boards')
