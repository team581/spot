"""Fetch-inspired design pass; shared data for Penpot and portable references."""
from pathlib import Path
import json
P=Path(__file__).parent
# Outline navigation icons remain editable SVG paths in Penpot.
PATHS={
'Overview':'<path d="M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/>',
'Cameras':'<rect x="3" y="6" width="18" height="14" rx="2"/><path d="m8 6 1-3h6l1 3"/><circle cx="12" cy="13" r="4"/>',
'Unassigned':'<path d="M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-6 6v4m6-4h5m-2.5-2.5v5"/>',
'Calibration':'<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 1v6m0 10v6M1 12h6m10 0h6"/>',
'Network & System':'<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01m5-11h6m-6 11h6"/>',
'Docs':'<path d="M12 5c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-4-1-7-1-10 1Zm0 0v15"/>'}
REMOVE={
'BLAZING BULLDOGS','All configured roles · required-camera readiness',
'Solver output is separate from robot fusion.',
'Cached profiles are labeled when the robot is offline. No role is chosen automatically.',
'One board can move between views. Validation capture is a separate step.',
'All selected results must pass before a group is activated.',
'Capture → Fit → Validate → Stage → Await acknowledgement → Applied',
'Applying is pending until the service confirms the active generation.',
'Coverage alone cannot pass calibration. Physical robot-pose checks remain a separate acceptance gate.',
'Diagnostics · read-only network configuration',
'Packaged locally · available without internet',
'Plug in → Assign → Calibrate → Verify',
'No mount values are editable here.',
'Read from the current robot manifest.',
'Metadata includes device identity, optical signature, board, model, build and content hash.',
'*Provisional burgundy accent. Replace with approved team colors/logo before final UI sign-off.',
'Viewing available · robot enabled',
'Bounded recording · no continuous verbose capture',
'1 physical device discovered · assignments saved for this robot profile'}
REPLACE={
'Offseason / Vision':'Offseason',
'rear-right is missing. Healthy cameras continue under the robot’s fusion policy.':'rear-right missing · 3 of 4 required cameras ready',
'Check USB power and the saved binding.':'Check USB power / binding',
'Overlays hidden · last frame 2.4 s ago':'Last frame 2.4 s ago · overlays hidden',
'Duplicate serial: this assignment follows USB port 1-3.1.':'Duplicate serial · bound to USB port 1-3.1',
'If this device moves to another port, identify its preview and reassign it.':'Reassign after moving ports.',
'Preview-confirm the physical camera':'Confirm camera',
'Available roles from robot code':'Available roles · from code',
'Group apply blocked: front-right validation failed. Active gen-07 is unchanged.':'Apply blocked · front-right validation failed · gen-07 active',
'front-right: capture sharper validation views near the image edges, then retry.':'front-right · retry with sharper edge views',
'Setup locked while enabled. Controls unlock only after confirmed disabled state.':'Robot enabled · setup locked',
'Illustrative frame reference · not a measured mount':'Frame reference',
'Running beta.01 · abc1234 · monotonic uptime 12 min.':'beta.01 · abc1234 · uptime 12 min',
'Cached profile · setup remains locked until explicit standalone setup.':'Cached profile · setup locked',
'Frame age 1.2 s · overlays hidden · capture progression stalled.':'Frame stalled · age 1.2 s · overlays hidden',
'Settings changed in another browser. Your draft is preserved.':'Settings changed in another browser · draft preserved',
'Activation pending. “Applied” appears only after service acknowledgement.':'Awaiting activation acknowledgement',
'gen-08 acknowledged. Saved values and applied readback match.':'gen-08 acknowledged · readback verified',
'Implementation reference · all telemetry, roles, release IDs and numerical examples are illustrative.':'Design reference · sample data',
'Theme / isolated tokens':'Theme',
'Team accent*':'Team accent',
'Configured / discovered endpoint':'Configured / discovered endpoint'}
COLORS={'#17212D':'#202226','#C4CCD5':'#66696E','#B32636':'#591616','#FAECEE':'#F6EEEE','#323A45':'#591616','#19232F':'#202226','#66717D':'#66696E','#36414D':'#D9DADD'}
def icon_svg(name,color):return f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'+PATHS[name]+'</svg>'
def restyle(boards):
 logo=(P/'blazing-bulldogs.svg').read_text()
 for b in boards:
  compact=b['name'].startswith('08');found=b['name'].startswith('10');out=[]
  for a in b['shapes']:
   a=a.copy()
   if a['type']=='text':
    if a['text'] in REMOVE or a['text']=='581':continue
    if compact and a['text'] in ['O','C','K','N','?']:continue
    a['text']=REPLACE.get(a['text'],a['text']);a['name']=a['text']
    if a['text']=='Spot':a.update(x=72,y=29,size=24,fill='#202226',w=130)
    if not found and not compact and a['x']==24 and a['y'] in [132,184,377,437,489,541]:a['x']=52;a['w']=152
    if not found and not compact and a['text'].startswith('  '):a['x']=46;a['w']=156
    if not found and not compact and a['x']<=52 and a['y'] in [132,184,229,266,303,340,377,437,489,541]:a['fill']='#FFFFFF' if a['weight']==600 else '#66696E'
    if a['fill']=='#FFFFFF' and a['text'] in ['BLAZING BULLDOGS']:a['fill']='#66696E'
   if a['type']=='rect':
    if (a['x'],a['y'],a['w'],a['h']) in [(24,27,38,38),(17,20,38,38)]:continue
    if a['x']==12 and a['w']==3 and a['h']==37:continue
    if a['x']==0 and a['y']==0 and a['w'] in [216,72]:a['fill']='#FFFFFF'
   # Keep dark image schematic regions dark while recoloring the app chrome.
   if a['fill'] in COLORS and not (a['type']=='rect' and a['fill']=='#17212D' and a['x']>216):a['fill']=COLORS[a['fill']]
   out.append(a)
  if not found:
   out.append(dict(type='svg',x=17 if compact else 20,y=22,w=40,h=40,svg=logo,name='Blazing Bulldogs logo'))
   if not compact:out.append(dict(type='rect',x=215,y=0,w=1,h=960,fill='#D9DADD',r=0,stroke=None,name='Sidebar border'))
   else:out.append(dict(type='rect',x=71,y=0,w=1,h=960,fill='#D9DADD',r=0,stroke=None,name='Sidebar border'))
   nav=[('Overview',132),('Cameras',184),('Unassigned',377),('Calibration',437),('Network & System',489),('Docs',541)]
   if compact:nav=[('Overview',132),('Cameras',192),('Calibration',252),('Network & System',312),('Docs',372)]
   for label,y in nav:
    chosen=any(a['type']=='text' and a['text'].strip().startswith(label) and a['weight']==600 and a.get('y')==y for a in out)
    out.append(dict(type='svg',x=25 if compact else 24,y=y-3,w=20,h=20,svg=icon_svg(label,'#FFFFFF' if chosen else '#66696E'),name='Icon / '+label))
  b['shapes']=out
 return boards
if __name__=='__main__':
 print('Import restyle() from build_design.py.')
