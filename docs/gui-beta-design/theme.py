"""Semantic dark palette for the GUI design reference."""
import copy,re
DARK={'#F4F5F7':'#10151C','#FFFFFF':'#171E27','#202226':'#E6EDF3','#66696E':'#A2ADB9','#DEE3E8':'#303947','#591616':'#8C3D46','#F6EEEE':'#342229','#226844':'#79D6A5','#EAF4EE':'#183529','#825A16':'#E5BA72','#FFF4DF':'#352B1C','#255A86':'#88B9ED','#EAF2F9':'#1C3044','#F8F9FA':'#131A23','#EBEEF1':'#1D2631','#E1E5E9':'#303B48','#949BA4':'#B2BAC5','#BFC5CC':'#505B69'}
def dark_boards(boards):
 out=copy.deepcopy(boards)
 for b in out:
  b['name']='Dark / '+b['name']
  feeds=[a for a in b['shapes'] if a['name']=='Camera feed']
  for a in b['shapes']:
   if a['name']=='Blazing Bulldogs logo':continue
   inside=any(a['x']>=f['x'] and a['y']>=f['y'] and a['x']+a['w']<=f['x']+f['w'] and a['y']+a['h']<=f['y']+f['h'] for f in feeds)
   if inside:continue
   if a['type']=='svg':
    a['svg']=re.sub(r'#[0-9A-Fa-f]{6}',lambda m:('#FFFFFF' if m[0].upper()=='#FFFFFF' else '#E9ABB3' if m[0].upper()=='#591616' else DARK.get(m[0].upper(),m[0])),a['svg']);continue
   if a['type']=='text' and a['fill']=='#FFFFFF':pass
   elif a['type']=='text' and a['fill']=='#591616':a['fill']='#E9ABB3'
   else:a['fill']=DARK.get(a['fill'],a['fill'])
   if a.get('stroke'):a['stroke']='#E9ABB3' if a['stroke']=='#591616' else DARK.get(a['stroke'],a['stroke'])
   if a['name']=='Input caret / end':a['fill']='#E9ABB3'
 return out

def theme_menus(light,dark):
 out=[]
 paths=['<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>','<path d="M20.5 14A9 9 0 0 1 10 3a9 9 0 1 0 10.5 11Z"/>','<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M12 17v4m-4 0h8"/>']
 for is_dark,base in [(False,light[0]),(True,dark[0])]:
  b=copy.deepcopy(base);b['name']=('Dark / ' if is_dark else '')+'12 Theme menu · Auto';sh=b['shapes'];surface='#171E27' if is_dark else '#FFFFFF';border='#303947' if is_dark else '#DEE3E8';muted='#A2ADB9' if is_dark else '#66696E';selected='#342229' if is_dark else '#F6EEEE';accent='#E9ABB3' if is_dark else '#591616'
  sh.append(dict(type='rect',x=20,y=687,w=160,h=56,fill=surface,r=10,stroke=border,name='Theme menu'))
  for i,label in enumerate(['Light','Dark','Auto']):
   x=28+i*48
   if i==2:sh.append(dict(type='rect',x=x,y=697,w=40,h=36,fill=selected,r=7,stroke=None,name='Theme / Auto / selected'))
   raw=f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{accent if i==2 else muted}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'+paths[i]+'</svg>'
   sh.append(dict(type='svg',x=x+9,y=704,w=22,h=22,svg=raw,name='Theme option / '+label))
  out.append(b)
 return out
