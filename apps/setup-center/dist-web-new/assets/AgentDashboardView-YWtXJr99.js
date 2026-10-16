import{u as Ft,r as b,s as Ot,j as i,o as Xt,A as Gt,w as Yt,x as Ht,y as Vt}from"./index-D01sJyOg.js";const It=new Map;function ut(w){const j=It.get(w);if(j)return j;let g=w.replace("#","");g.length===3&&(g=g[0]+g[0]+g[1]+g[1]+g[2]+g[2]);const S=parseInt(g.substring(0,2),16),T=parseInt(g.substring(2,4),16),F=parseInt(g.substring(4,6),16),P=[Number.isFinite(S)?S:107,Number.isFinite(T)?T:114,Number.isFinite(F)?F:128];return It.set(w,P),P}function mt(w,j,g){return w+(j-w)*g}function Pt(){const w=getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();if(!w)return!0;if(w.startsWith("#")){const[j,g,S]=ut(w);return j*.299+g*.587+S*.114<128}return document.documentElement.dataset.theme==="dark"}const H=()=>performance.now()/1e3,Bt={web_search:"S",browser_navigate:"W",browser_snapshot:"C",browser:"W",file_read:"F",read_file:"F",file_write:"W",write_file:"W",execute_command:"!",create_agent:"A",delegate_to_agent:">",list_skills:"#",memory_read:"M",memory_write:"M",create_todo:"T",mcp_call:"P",send_message:">",desktop_click:"D",desktop_type:"K",desktop_action:"D"};function Kt(w){const j=w.toLowerCase();for(const[g,S]of Object.entries(Bt))if(j.includes(g))return S;return"*"}const Ut=Object.fromEntries(Object.entries(Vt).map(([w,j])=>[w,j.path])),Ct=new Map;function Jt(w,j){const g=`${w}:${j}`,S=Ct.get(g);if(S)return S.complete?S:null;const T=Ut[w];if(!T)return null;const F=`<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="${j}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${T}"/></svg>`,P=new Image;return P.src="data:image/svg+xml;charset=utf-8,"+encodeURIComponent(F),Ct.set(g,P),null}const Nt=new Map;function Qt(w,j){const g=`${w}:${j}`,S=Nt.get(g);if(S)return S;const T=j*2,F=document.createElement("canvas");F.width=T,F.height=T;const P=F.getContext("2d");return P&&(P.font=`${j}px "Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif`,P.textAlign="center",P.textBaseline="middle",P.fillText(w,T/2,T/2+j*.06)),Nt.set(g,F),F}const Tt=new Map;function Zt(w,j){const g=Ht(w,j),S=Tt.get(g);if(S)return S.complete&&S.naturalWidth>0?S:null;const T=new Image;return T.src=g,Tt.set(g,T),null}function ae({apiBaseUrl:w="http://127.0.0.1:18900",visible:j=!0}){const{t:g}=Ft(),S=b.useRef(null),T=b.useRef(null),F=b.useRef(null),P=b.useRef(new Map),bt=b.useRef([]),pt=b.useRef([]),At=b.useRef([]),yt=b.useRef([]),K=b.useRef(0),gt=b.useRef(!0),U=b.useRef({w:800,h:500}),Et=b.useRef(0),vt=b.useRef(new Map),ht=b.useRef(!1),Mt=b.useRef(0),V=b.useRef(null),[L,zt]=b.useState(null),[et,it]=b.useState(null),[$t,wt]=b.useState(null),[Lt,Dt]=b.useState(0),kt=b.useRef(0),ct=b.useCallback(async()=>{try{const y=await(await Ot(`${w}/api/agents/topology`)).json();zt(y)}catch{}},[w]);b.useEffect(()=>{if(!j)return;ct();let r;const y=()=>{const h=Array.from(P.current.values()).some(p=>p.status==="running");r=setTimeout(()=>{ct().then(y)},h?3e3:1e4)};return y(),()=>clearTimeout(r)},[j,ct]),b.useEffect(()=>{if(!L)return;const r=P.current,y=new Set(L.nodes.map(l=>l.id));yt.current=L.edges;const h=U.current.w,p=U.current.h,W=h/2,X=p/2;for(const l of L.nodes){const e=r.get(l.id);if(e){if(l.tools_total>e.prevToolsTotal){e.ripples.push({t:H(),maxR:60});const v=l.tools_total-e.prevToolsTotal,x=l.tools_executed.slice(-v);for(const A of x)bt.current.push({id:`${l.id}::tool::${A}::${Math.random()}`,parentId:l.id,name:A,x:e.x,y:e.y,angle:Math.random()*Math.PI*2,dist:50+Math.random()*25,r:6,opacity:0,birthT:H(),deathT:H()+10,color:l.color||"#6b7280"})}const M=l.status==="dormant"?18:l.is_sub_agent?22:32;Object.assign(e,{...l,targetR:M,prevToolsTotal:l.tools_total,rgb:ut(l.color||"#6b7280")}),l.status==="completed"&&!e.deathT&&(e.deathT=H()+15)}else{const M=l.parent_id?r.get(l.parent_id):null;let v,x;if(l.is_sub_agent){const R=Array.from(r.values()).filter(G=>G.parent_id===l.parent_id&&G.is_sub_agent),N=L.nodes.filter(G=>G.parent_id===l.parent_id&&G.is_sub_agent),C=N.filter(G=>!r.has(G.id)).indexOf(l),O=R.length+Math.max(C,0),Z=Math.max(N.length,O+1),at=M?M.x:W,Y=M?M.y:X,ot=Math.max(120,Z*50),tt=Math.PI*2/Math.max(Z,1)*O-Math.PI/2;v=at+Math.cos(tt)*ot,x=Y+Math.sin(tt)*ot}else if(l.status==="dormant"){const R=Math.random();R<.25?(v=60+Math.random()*80,x=60+Math.random()*(p-120)):R<.5?(v=h-60-Math.random()*80,x=60+Math.random()*(p-120)):R<.75?(v=60+Math.random()*(h-120),x=60+Math.random()*80):(v=60+Math.random()*(h-120),x=p-60-Math.random()*80)}else{const R=L.nodes.filter(C=>!C.parent_id&&!C.is_sub_agent&&C.status!=="dormant"),N=R.indexOf(l),Q=R.length||1;if(Q===1)v=W,x=X;else{const C=Math.PI*2*N/Q-Math.PI/2,O=Math.min(h,p)*.18;v=W+Math.cos(C)*O,x=X+Math.sin(C)*O}}const A=l.status==="dormant"?18:l.is_sub_agent?22:32;r.set(l.id,{...l,x:v,y:x,vx:(Math.random()-.5)*.5,vy:(Math.random()-.5)*.5,targetR:A,r:0,opacity:0,birthT:H(),deathT:l.status==="completed"?H()+15:null,ripples:[],prevToolsTotal:l.tools_total,rgb:ut(l.color||"#6b7280")})}}for(const[l,e]of r)!y.has(l)&&!e.deathT&&(e.deathT=H()+2)},[L]),b.useEffect(()=>{const r=U.current.w,y=U.current.h;if(pt.current.length===0)for(let h=0;h<20;h++)pt.current.push({x:Math.random()*r,y:Math.random()*y,vx:(Math.random()-.5)*.3,vy:(Math.random()-.5)*.3,size:1+Math.random()*2,alpha:.15+Math.random()*.2})},[]),b.useEffect(()=>{const r=()=>{const y=T.current;if(!y)return;const h=y.getBoundingClientRect();U.current={w:h.width,h:h.height};const p=S.current;p&&(p.width=h.width*devicePixelRatio,p.height=h.height*devicePixelRatio,p.style.width=h.width+"px",p.style.height=h.height+"px")};return r(),window.addEventListener("resize",r),()=>window.removeEventListener("resize",r)},[j,w]),b.useEffect(()=>{if(!j)return;gt.current=Pt();const r=setInterval(()=>{gt.current=Pt()},2e3),y=()=>{ht.current=document.hidden};document.addEventListener("visibilitychange",y),ht.current=document.hidden;const h=()=>{var Rt;if(ht.current){K.current=requestAnimationFrame(h);return}const p=H(),X=!!V.current?0:1/60;if(p-Mt.current<X){K.current=requestAnimationFrame(h);return}Mt.current=p;const l=S.current;if(!l){K.current=requestAnimationFrame(h);return}const e=l.getContext("2d");if(!e){K.current=requestAnimationFrame(h);return}const M=devicePixelRatio,v=U.current.w,x=U.current.h,A=gt.current,R=P.current,N=Array.from(R.values()),Q=yt.current,C=pt.current,O=At.current,Z=v/2,at=x/2,Y=40;for(let t=0;t<N.length;t++){const n=N[t],a=n.status==="dormant";for(let o=t+1;o<N.length;o++){const s=N[o],c=s.status==="dormant";let $=n.x-s.x,k=n.y-s.y,u=Math.sqrt($*$+k*k)||1;const _=n.is_sub_agent&&s.is_sub_agent&&n.parent_id&&n.parent_id===s.parent_id,I=!n.is_sub_agent&&!s.is_sub_agent&&!a&&!c,E=!a&&!c,d=_?3e4:I?35e3:E?28e3:a&&c?6e3:1e4,f=_?120:I?140:E?110:a&&c?80:100;u<f&&(u=f);const m=d/(u*u),z=$/u*m,q=k/u*m;n.vx+=z*.016,n.vy+=q*.016,s.vx-=z*.016,s.vy-=q*.016}if(!a){const o=n.parent_id?R.get(n.parent_id):null;if(n.is_sub_agent){const s=N.filter(m=>m.parent_id===n.parent_id&&m.is_sub_agent),c=s.indexOf(n),$=s.length||1,k=o?o.x:Z,u=o?o.y:at,_=Math.max(120,$*50),E=Math.PI*2/Math.max($,1)*c-Math.PI/2,d=k+Math.cos(E)*_,f=u+Math.sin(E)*_;n.vx+=(d-n.x)*.006,n.vy+=(f-n.y)*.006}else{const s=N.filter(_=>!_.is_sub_agent&&_.status!=="dormant"),c=s.indexOf(n),$=s.length||1;let k=Z,u=at;if($>1){const _=Math.PI*2*c/$-Math.PI/2,I=Math.min(v,x)*.15;k=Z+Math.cos(_)*I,u=at+Math.sin(_)*I}n.vx+=(k-n.x)*.003,n.vy+=(u-n.y)*.003}}}for(const t of Q){const n=R.get(t.from),a=R.get(t.to);if(!n||!a)continue;const o=a.x-n.x,s=a.y-n.y,c=Math.sqrt(o*o+s*s)||1,k=(c-150)*.005,u=o/c*k,_=s/c*k;n.vx+=u,n.vy+=_,a.vx-=u,a.vy-=_}const ot=(Rt=V.current)==null?void 0:Rt.nodeId;for(const t of N){if(t.id===ot)t.vx=0,t.vy=0,t.x=Math.max(Y,Math.min(v-Y,t.x)),t.y=Math.max(Y,Math.min(x-Y,t.y));else{const n=t.status==="dormant";t.vx*=n?.96:.88,t.vy*=n?.96:.88,n||(t.vx+=(Math.random()-.5)*.04,t.vy+=(Math.random()-.5)*.04),t.x+=t.vx,t.y+=t.vy,t.x=Math.max(Y,Math.min(v-Y,t.x)),t.y=Math.max(Y,Math.min(x-Y,t.y))}if(t.deathT&&p>t.deathT)t.opacity=Math.max(0,t.opacity-.02),t.r=Math.max(0,t.r-.3),t.opacity<=0&&R.delete(t.id);else{t.r=mt(t.r,t.targetR,.08);const n=t.status==="dormant"?.75:1;t.opacity=Math.min(n,t.opacity+.04)}t.ripples=t.ripples.filter(n=>p-n.t<1.5)}for(const t of Q){const n=R.get(t.from),a=R.get(t.to);if(!(!n||!a)&&(n.status==="running"||a.status==="running")){const o=`${t.from}->${t.to}`,s=vt.current.get(o)||0;p-s>1.5+Math.random()*.5&&(O.push({edge:t,t:0,speed:.6+Math.random()*.3}),vt.current.set(o,p))}}for(let t=O.length-1;t>=0;t--)if(O[t].t+=.016*O[t].speed,O[t].t>1){const n=R.get(O[t].edge.to);n&&n.ripples.push({t:p,maxR:30}),O.splice(t,1)}const rt=bt.current;for(let t=rt.length-1;t>=0;t--){const n=rt[t],a=R.get(n.parentId);if(!a||p>n.deathT+2&&n.opacity<=0){rt.splice(t,1);continue}n.angle+=.012,n.x=a.x+Math.cos(n.angle)*n.dist,n.y=a.y+Math.sin(n.angle)*n.dist,p<n.birthT+.5?n.opacity=Math.min(.9,(p-n.birthT)/.5):p>n.deathT&&(n.opacity=Math.max(0,n.opacity-.015))}for(const t of C){t.vx+=(Math.random()-.5)*.02,t.vy+=(Math.random()-.5)*.02;for(const n of N){if(n.status!=="running")continue;const a=n.x-t.x,o=n.y-t.y,s=Math.sqrt(a*a+o*o)||1;s<200&&(t.vx+=a/s*.015,t.vy+=o/s*.015)}t.vx*=.97,t.vy*=.97,t.x+=t.vx,t.y+=t.vy,t.x<0&&(t.x=v),t.x>v&&(t.x=0),t.y<0&&(t.y=x),t.y>x&&(t.y=0)}e.save(),e.scale(M,M),e.clearRect(0,0,v,x),Et.current+=.016;for(const t of C)e.beginPath(),e.arc(t.x,t.y,t.size,0,Math.PI*2),A?e.fillStyle=`rgba(255,255,255,${t.alpha*.5})`:e.fillStyle=`rgba(0,0,0,${t.alpha*.2})`,e.fill();e.lineWidth=.5;const tt=[[],[],[]];let G=0;const _t=30;for(let t=0;t<C.length&&G<_t;t++)for(let n=t+1;n<C.length&&G<_t;n++){const a=C[t].x-C[n].x,o=C[t].y-C[n].y,s=Math.sqrt(a*a+o*o);if(s<40){const c=(1-s/40)*.06,$=c>.04?2:c>.02?1:0;tt[$].push([C[t].x,C[t].y,C[n].x,C[n].y]),G++}}const qt=[.01,.03,.05];for(let t=0;t<3;t++){if(tt[t].length===0)continue;e.beginPath();for(const[a,o,s,c]of tt[t])e.moveTo(a,o),e.lineTo(s,c);const n=qt[t];e.strokeStyle=A?`rgba(255,255,255,${n})`:`rgba(0,0,0,${n*.5})`,e.stroke()}for(const t of N){if(t.status!=="dormant"||t.opacity<=0)continue;const[n,a,o]=t.rgb;e.beginPath();let s=!1;for(const c of C){const $=t.x-c.x,k=t.y-c.y;Math.sqrt($*$+k*k)<70&&(e.moveTo(t.x,t.y),e.lineTo(c.x,c.y),s=!0)}s&&(e.strokeStyle=`rgba(${n},${a},${o},${.04*t.opacity})`,e.stroke())}const lt=N.filter(t=>t.status==="dormant"&&t.opacity>0);e.lineWidth=1,e.setLineDash([5,8]);for(let t=0;t<lt.length;t++)for(let n=t+1;n<lt.length;n++){const a=lt[t],o=lt[n],s=o.x-a.x,c=o.y-a.y,$=Math.sqrt(s*s+c*c);if($>300)continue;const[k,u,_]=a.rgb,[I,E,d]=o.rgb,m=(1-$/300)*.12*Math.min(a.opacity,o.opacity),z=k+I>>1,q=u+E>>1,B=_+d>>1;e.beginPath(),e.moveTo(a.x,a.y),e.lineTo(o.x,o.y),e.strokeStyle=`rgba(${z},${q},${B},${m})`,e.stroke()}e.setLineDash([]);for(const t of Q){const n=R.get(t.from),a=R.get(t.to);if(!n||!a||n.opacity<=0||a.opacity<=0)continue;const o=a.x-n.x,s=a.y-n.y,c={x:-s*.15,y:o*.15},$=Math.sin(p*.25+n.x*.007)*12,k=Math.cos(p*.3+a.y*.009)*12,u=n.x+o*.3+c.x+$,_=n.y+s*.3+c.y+$,I=n.x+o*.7-c.x+k,E=n.y+s*.7-c.y+k,[d,f,m]=n.rgb,[z,q,B]=a.rgb,St=n.status==="running"||a.status==="running",xt=(St?.7:.2)*Math.min(n.opacity,a.opacity),dt=e.createLinearGradient(n.x,n.y,a.x,a.y);dt.addColorStop(0,`rgba(${d},${f},${m},${xt})`),dt.addColorStop(.5,`rgba(${d+z>>1},${f+q>>1},${m+B>>1},${xt*1.2})`),dt.addColorStop(1,`rgba(${z},${q},${B},${xt})`),e.beginPath(),e.moveTo(n.x,n.y),e.bezierCurveTo(u,_,I,E,a.x,a.y),e.strokeStyle=dt,e.lineWidth=St?3:1.5,e.stroke(),t._cp={cp1x:u,cp1y:_,cp2x:I,cp2y:E}}for(const t of O){const n=R.get(t.edge.from),a=R.get(t.edge.to);if(!n||!a)continue;const o=t.edge._cp,s=d=>{if(o){const f=1-d;return{x:f*f*f*n.x+3*f*f*d*o.cp1x+3*f*d*d*o.cp2x+d*d*d*a.x,y:f*f*f*n.y+3*f*f*d*o.cp1y+3*f*d*d*o.cp2y+d*d*d*a.y}}return{x:mt(n.x,a.x,d),y:mt(n.y,a.y,d)}},[c,$,k]=n.rgb,u=Math.sin(t.t*Math.PI)*.95,_=6;for(let d=_;d>=0;d--){const f=Math.max(0,t.t-d*.03),m=s(f),z=(1-d/_)*u,q=4+(1-d/_)*7,B=e.createRadialGradient(m.x,m.y,0,m.x,m.y,q);B.addColorStop(0,`rgba(${c},${$},${k},${z*.8})`),B.addColorStop(1,`rgba(${c},${$},${k},0)`),e.beginPath(),e.arc(m.x,m.y,q,0,Math.PI*2),e.fillStyle=B,e.fill()}const I=s(t.t),E=e.createRadialGradient(I.x,I.y,0,I.x,I.y,16);E.addColorStop(0,`rgba(${c},${$},${k},${u})`),E.addColorStop(.35,`rgba(${c},${$},${k},${u*.5})`),E.addColorStop(1,`rgba(${c},${$},${k},0)`),e.beginPath(),e.arc(I.x,I.y,16,0,Math.PI*2),e.fillStyle=E,e.fill(),e.beginPath(),e.arc(I.x,I.y,3.5,0,Math.PI*2),e.fillStyle=`rgba(255,255,255,${u*.9})`,e.fill()}for(const t of N){if(t.opacity<=0||t.r<=0)continue;const[n,a,o]=t.rgb,s=t.status==="running",c=t.status==="dormant",$=t.status==="error",k=s?1+.1*Math.sin(p*2.5+t.x*.01):c?1+.04*Math.sin(p*.6+t.x*.005):1,u=t.r*k,_=t.id===ot;if(s||_){const d=u+(_?18:12),f=_?.5:.35,m=e.createRadialGradient(t.x,t.y,u,t.x,t.y,d);m.addColorStop(0,`rgba(${n},${a},${o},${t.opacity*f})`),m.addColorStop(1,`rgba(${n},${a},${o},0)`),e.beginPath(),e.arc(t.x,t.y,d,0,Math.PI*2),e.fillStyle=m,e.fill()}for(const d of t.ripples){const f=p-d.t,m=u+f*d.maxR,z=Math.max(0,.5*(1-f/1.5))*t.opacity;e.beginPath(),e.arc(t.x,t.y,m,0,Math.PI*2),e.strokeStyle=`rgba(${n},${a},${o},${z})`,e.lineWidth=2,e.stroke()}const I=t.opacity*(s?.9:c?.35:.6);e.beginPath(),e.arc(t.x,t.y,u,0,Math.PI*2),e.fillStyle=A?`rgba(${n},${a},${o},${I})`:`rgba(${n},${a},${o},${I*.85})`,e.fill();const E=t.opacity*(s?.9:c?.3:.5);if(e.beginPath(),e.arc(t.x,t.y,u,0,Math.PI*2),e.strokeStyle=A?`rgba(${Math.min(255,n+60)},${Math.min(255,a+60)},${Math.min(255,o+60)},${E})`:`rgba(${n},${a},${o},${E})`,e.lineWidth=c?1:2,c&&e.setLineDash([3,3]),e.stroke(),e.setLineDash([]),!c){const d=e.createRadialGradient(t.x-u*.3,t.y-u*.3,0,t.x-u*.3,t.y-u*.3,u*.6);d.addColorStop(0,`rgba(255,255,255,${t.opacity*(s?.35:.15)})`),d.addColorStop(1,"rgba(255,255,255,0)"),e.beginPath(),e.arc(t.x,t.y,u,0,Math.PI*2),e.fillStyle=d,e.fill()}if($&&(e.beginPath(),e.arc(t.x,t.y,u+2,0,Math.PI*2),e.strokeStyle=`rgba(239,68,68,${.5+.3*Math.sin(p*6)})`,e.lineWidth=2.5,e.stroke()),s){const d=p*3;e.beginPath(),e.arc(t.x,t.y,u+5,d,d+Math.PI*.6),e.strokeStyle=`rgba(${n},${a},${o},${t.opacity*.7})`,e.lineWidth=2.5,e.lineCap="round",e.stroke(),e.lineCap="butt"}if(t.icon&&u>8){const d=t.opacity*(c?.6:.95);if(e.save(),e.globalAlpha=d,Yt(t.icon)){const f=Zt(t.icon,w);if(f){const m=u*1.65;e.save(),e.beginPath(),e.arc(t.x,t.y,m/2,0,Math.PI*2),e.clip(),e.drawImage(f,t.x-m/2,t.y-m/2,m,m),e.restore()}}else if(t.icon.startsWith("svg:")){const f=t.icon.slice(4),z=Jt(f,A?"rgba(255,255,255,0.9)":"rgba(255,255,255,0.95)");if(z){const q=u*1.2;e.drawImage(z,t.x-q/2,t.y-q/2,q,q)}}else{const f=Math.round(u*(c?.9:1.1)),m=Qt(t.icon,f),z=m.width/2;e.drawImage(m,t.x-z,t.y-z)}e.restore()}}for(const t of rt){if(t.opacity<=0)continue;const n=R.get(t.parentId);if(!n)continue;const[a,o,s]=ut(t.color);e.beginPath(),e.moveTo(n.x,n.y),e.lineTo(t.x,t.y),e.strokeStyle=`rgba(${a},${o},${s},${t.opacity*.35})`,e.lineWidth=1,e.setLineDash([3,4]),e.stroke(),e.setLineDash([]),e.beginPath(),e.arc(t.x,t.y,t.r,0,Math.PI*2),e.fillStyle=`rgba(${a},${o},${s},${t.opacity*.6})`,e.fill(),e.strokeStyle=A?`rgba(255,255,255,${t.opacity*.4})`:`rgba(${a},${o},${s},${t.opacity*.5})`,e.lineWidth=1,e.stroke();const c=Kt(t.name);e.font="bold 9px system-ui, sans-serif",e.textAlign="center",e.fillStyle=A?`rgba(255,255,255,${t.opacity*.8})`:`rgba(0,0,0,${t.opacity*.7})`,e.fillText(`${c} ${t.name}`,t.x,t.y+t.r+12)}e.restore();const jt=F.current;let st=0;if(jt){const t=jt.children;let n=0;for(const a of N){if(a.opacity<=0||a.r<=0)continue;st++;const o=t[n];o&&(o.style.transform=`translate(${a.x}px, ${a.y+24}px) translateX(-50%)`,o.style.opacity=String(a.opacity)),n++}}else for(const t of N)t.opacity>0&&t.r>0&&st++;st!==kt.current&&(kt.current=st,Dt(st)),K.current=requestAnimationFrame(h)};return K.current=requestAnimationFrame(h),()=>{cancelAnimationFrame(K.current),clearInterval(r),document.removeEventListener("visibilitychange",y)}},[j]),b.useEffect(()=>{const r=y=>{y.key==="Escape"&&it(null)};return window.addEventListener("keydown",r),()=>window.removeEventListener("keydown",r)},[]);const nt=b.useCallback(r=>{const y=T.current;if(!y)return{x:0,y:0};const h=y.getBoundingClientRect();return{x:r.clientX-h.left,y:r.clientY-h.top}},[]),ft=b.useCallback((r,y)=>{const h=Array.from(P.current.values());for(let p=h.length-1;p>=0;p--){const W=h[p];if(W.opacity<=0||W.r<=0)continue;const X=r-W.x,l=y-W.y;if(X*X+l*l<=(W.r+8)*(W.r+8))return W}return null},[]);b.useEffect(()=>{const r=S.current;if(!r)return;const y=(e,M,v)=>{const x=P.current.get(e);x&&(V.current={nodeId:e,offsetX:M-x.x,offsetY:v-x.y,moved:!1},x.vx=0,x.vy=0)},h=e=>{const M=nt(e),v=ft(M.x,M.y);v&&(y(v.id,M.x,M.y),r.style.cursor="grabbing",e.preventDefault())},p=e=>{const M=V.current;if(M){const v=nt(e),x=P.current.get(M.nodeId);x&&(x.x=v.x-M.offsetX,x.y=v.y-M.offsetY,x.vx=0,x.vy=0,M.moved=!0);const A=T.current;A&&(A.style.cursor="grabbing")}else{const v=nt(e),x=ft(v.x,v.y);r.style.cursor=x?"grab":""}},W=()=>{if(V.current){const e=P.current.get(V.current.nodeId);e&&e.ripples.push({t:H(),maxR:40}),V.current=null,r.style.cursor="";const M=T.current;M&&(M.style.cursor="")}},X=e=>{const M=e.target.closest(".neural-label");if(!M)return;const v=Array.from(M.parentElement.children).indexOf(M),A=Array.from(P.current.values()).filter(N=>N.opacity>0&&N.r>0)[v];if(!A)return;const R=nt(e);y(A.id,R.x,R.y),e.preventDefault()},l=F.current;return r.addEventListener("mousedown",h),l==null||l.addEventListener("mousedown",X),window.addEventListener("mousemove",p),window.addEventListener("mouseup",W),()=>{r.removeEventListener("mousedown",h),l==null||l.removeEventListener("mousedown",X),window.removeEventListener("mousemove",p),window.removeEventListener("mouseup",W)}},[nt,ft]);const Wt=b.useMemo(()=>{const r=P.current;return Array.from(r.values()).filter(y=>y.opacity>0&&y.r>0)},[L,et,$t,Lt]),J=L==null?void 0:L.stats,D=et&&P.current.get(et)||null;return i.jsxs("div",{ref:T,className:"neural-dash",onClick:()=>it(null),children:[i.jsx(te,{}),i.jsx("canvas",{ref:S,className:"neural-canvas"}),i.jsx("div",{ref:F,className:"neural-overlay",children:Wt.map(r=>i.jsxs("div",{className:`neural-label ${r.status} ${$t===r.id?"hovered":""} ${et===r.id?"selected":""}`,style:{"--nc":r.color},onMouseEnter:()=>wt(r.id),onMouseLeave:()=>wt(null),onClick:y=>{var h;y.stopPropagation(),!((h=V.current)!=null&&h.moved)&&it(r.id===et?null:r.id)},children:[i.jsx("span",{className:"neural-name",children:r.name}),r.status==="running"&&i.jsx("span",{className:"neural-status-dot running"}),r.status==="error"&&i.jsx("span",{className:"neural-status-dot error"}),r.is_sub_agent&&i.jsx("span",{className:"neural-sub-badge",children:"SUB"})]},r.id))}),i.jsxs("div",{className:"neural-hud",children:[i.jsx("div",{className:"neural-hud-stats",children:J&&J.total_requests>0?i.jsxs(i.Fragment,{children:[i.jsxs("span",{children:[J.total_requests," ",g("dashboard.requests")]}),i.jsx("span",{className:"neural-hud-sep",children:"·"}),i.jsxs("span",{style:{color:"#10b981"},children:[J.total_requests>0?Math.round(J.successful/J.total_requests*100):0,"%"]}),i.jsx("span",{className:"neural-hud-sep",children:"·"}),i.jsxs("span",{children:[(J.avg_latency_ms/1e3).toFixed(1),"s"]})]}):i.jsx("span",{style:{opacity:.4},children:g("dashboard.noActivity")})}),i.jsx("button",{className:"neural-hud-btn",onClick:ct,title:g("dashboard.refresh"),children:i.jsx(Xt,{size:14})})]}),(!L||L.nodes.length===0)&&i.jsxs("div",{className:"neural-empty",children:[i.jsx("div",{className:"neural-empty-ring"}),i.jsx("div",{className:"neural-empty-text",children:g("dashboard.waiting")})]}),L&&L.nodes.length>0&&L.nodes.every(r=>r.status==="dormant")&&i.jsx("div",{className:"neural-dormant-hint",children:g("dashboard.allDormant")}),D&&i.jsxs("div",{className:"neural-detail",onClick:r=>r.stopPropagation(),children:[i.jsxs("div",{className:"neural-detail-header",style:{"--nc":D.color},children:[i.jsx("span",{className:"neural-detail-icon",children:i.jsx(Gt,{icon:D.icon,size:28,apiBaseUrl:w})}),i.jsxs("div",{children:[i.jsx("div",{className:"neural-detail-name",children:D.name}),i.jsx("div",{className:"neural-detail-pid",children:D.profile_id})]}),i.jsx("span",{className:`neural-detail-badge ${D.status}`,children:g(`dashboard.status_${D.status}`)})]}),D.conversation_title&&i.jsxs("div",{className:"neural-detail-section",children:[i.jsx("div",{className:"neural-detail-label",children:g("dashboard.conversation")}),i.jsx("div",{className:"neural-detail-conv",children:D.conversation_title})]}),i.jsxs("div",{className:"neural-detail-section",children:[i.jsx("div",{className:"neural-detail-label",children:g("dashboard.progress")}),i.jsxs("div",{className:"neural-detail-meta",children:[i.jsxs("span",{children:["Iter #",D.iteration]}),i.jsxs("span",{children:[D.tools_total," ",g("dashboard.tools")]}),i.jsxs("span",{children:[D.elapsed_s,"s"]})]})]}),D.tools_executed.length>0&&i.jsxs("div",{className:"neural-detail-section",children:[i.jsx("div",{className:"neural-detail-label",children:g("dashboard.recentTools")}),i.jsx("div",{className:"neural-detail-timeline",children:D.tools_executed.map((r,y)=>i.jsxs("div",{className:"neural-detail-tool",children:[i.jsx("span",{className:"neural-detail-tool-dot",style:{background:D.color}}),i.jsx("span",{children:r})]},y))})]}),i.jsx("button",{className:"neural-detail-close",onClick:()=>it(null),children:"ESC"})]})]})}function te(){return i.jsx("style",{children:`
      .neural-dash {
        position: relative;
        width: 100%;
        height: 100%;
        overflow: hidden;
        cursor: default;
        user-select: none;
        background: var(--bg, #fff);
      }
      .neural-canvas {
        position: absolute;
        inset: 0;
        z-index: 0;
      }
      .neural-overlay {
        position: absolute;
        inset: 0;
        z-index: 1;
        pointer-events: none;
      }
      .neural-label {
        position: absolute;
        left: 0; top: 0;
        pointer-events: all;
        cursor: grab;
        display: flex;
        align-items: center;
        gap: 5px;
        padding: 3px 10px 3px 6px;
        border-radius: 20px;
        background: rgba(15,15,25,0.7);
        border: 1px solid rgba(255,255,255,0.06);
        transform-origin: center center;
        transition: border-color 0.3s, box-shadow 0.3s;
        white-space: nowrap;
      }
      [data-theme="light"] .neural-label,
      :root:not([data-theme="dark"]) .neural-label {
        background: rgba(255,255,255,0.75);
        border: 1px solid rgba(0,0,0,0.08);
      }
      .neural-label.hovered, .neural-label.selected {
        border-color: var(--nc, #7c3aed);
        box-shadow: 0 0 12px rgba(124,58,237,0.2);
      }
      .neural-icon {
        font-size: 16px;
        line-height: 1;
      }
      .neural-name {
        font-size: 11px;
        font-weight: 600;
        opacity: 0.85;
      }
      .neural-status-dot {
        width: 6px; height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
      }
      .neural-status-dot.running {
        background: #10b981;
        box-shadow: 0 0 6px #10b981;
        animation: ndPulse 1.5s ease-in-out infinite;
      }
      .neural-status-dot.error {
        background: #ef4444;
        box-shadow: 0 0 6px #ef4444;
      }
      @keyframes ndPulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.5; transform: scale(1.5); }
      }
      .neural-sub-badge {
        font-size: 8px;
        font-weight: 700;
        padding: 1px 4px;
        border-radius: 4px;
        background: rgba(124,58,237,0.15);
        color: #a78bfa;
        letter-spacing: 0.5px;
      }

      /* HUD */
      .neural-hud {
        position: absolute;
        top: 14px; left: 14px; right: 14px;
        z-index: 2;
        display: flex;
        align-items: center;
        justify-content: space-between;
        pointer-events: none;
      }
      .neural-hud-stats {
        pointer-events: all;
        padding: 6px 14px;
        border-radius: 20px;
        background: rgba(0,0,0,0.3);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        font-size: 12px;
        font-weight: 600;
        color: rgba(255,255,255,0.8);
        display: flex;
        align-items: center;
        gap: 6px;
      }
      [data-theme="light"] .neural-hud-stats,
      :root:not([data-theme="dark"]) .neural-hud-stats {
        background: rgba(255,255,255,0.75);
        color: rgba(0,0,0,0.7);
        box-shadow: 0 1px 4px rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.06);
      }
      .neural-hud-sep { opacity: 0.3; }
      button.neural-hud-btn {
        pointer-events: all;
        width: 32px; height: 32px;
        padding: 0;
        border-radius: 50%;
        border: none;
        background: rgba(0,0,0,0.3);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        color: rgba(255,255,255,0.7);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s;
        letter-spacing: normal;
      }
      button.neural-hud-btn:hover { background: rgba(0,0,0,0.5); }
      [data-theme="light"] button.neural-hud-btn,
      :root:not([data-theme="dark"]) button.neural-hud-btn {
        background: rgba(255,255,255,0.75);
        color: rgba(0,0,0,0.55);
        box-shadow: 0 1px 4px rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.06);
      }
      [data-theme="light"] button.neural-hud-btn:hover,
      :root:not([data-theme="dark"]) button.neural-hud-btn:hover {
        background: rgba(255,255,255,0.92);
        color: rgba(0,0,0,0.75);
      }

      /* Empty state */
      .neural-empty {
        position: absolute;
        inset: 0; z-index: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        pointer-events: none;
      }
      .neural-empty-ring {
        width: 80px; height: 80px;
        border-radius: 50%;
        border: 1px solid rgba(124,58,237,0.12);
        animation: emptyPulse 4s ease-in-out infinite;
      }
      @keyframes emptyPulse {
        0%, 100% { transform: scale(1); opacity: 0.3; }
        50% { transform: scale(1.1); opacity: 0.15; }
      }
      .neural-empty-text {
        margin-top: 14px;
        font-size: 13px;
        font-weight: 500;
        opacity: 0.25;
      }

      /* Detail panel */
      .neural-detail {
        position: absolute;
        top: 60px;
        right: 14px;
        z-index: 3;
        width: 280px;
        max-height: calc(100% - 80px);
        overflow-y: auto;
        border-radius: 16px;
        background: rgba(10,14,26,0.75);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid rgba(255,255,255,0.08);
        padding: 18px;
        animation: detailSlide 0.25s ease-out;
      }
      [data-theme="light"] .neural-detail,
      :root:not([data-theme="dark"]) .neural-detail {
        background: rgba(255,255,255,0.8);
        border: 1px solid rgba(0,0,0,0.08);
      }
      @keyframes detailSlide {
        from { transform: translateX(20px); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
      }
      .neural-detail-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 16px;
      }
      .neural-detail-icon {
        font-size: 28px;
        width: 44px; height: 44px;
        border-radius: 12px;
        background: rgba(124,58,237,0.1);
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .neural-detail-name {
        font-weight: 700;
        font-size: 15px;
      }
      .neural-detail-pid {
        font-size: 10px;
        opacity: 0.4;
        font-family: monospace;
      }
      .neural-detail-badge {
        margin-left: auto;
        padding: 3px 8px;
        border-radius: 8px;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .neural-detail-badge.running { background: rgba(16,185,129,0.15); color: #10b981; }
      .neural-detail-badge.idle { background: rgba(107,114,128,0.15); color: #9ca3af; }
      .neural-detail-badge.completed { background: rgba(59,130,246,0.15); color: #60a5fa; }
      .neural-detail-badge.error { background: rgba(239,68,68,0.15); color: #f87171; }
      .neural-detail-badge.dormant { background: rgba(107,114,128,0.08); color: #6b7280; }

      .neural-label.dormant {
        opacity: 0.5;
      }
      .neural-label.dormant .neural-name {
        opacity: 0.6;
      }

      .neural-dormant-hint {
        position: absolute;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 1;
        font-size: 12px;
        font-weight: 500;
        opacity: 0.2;
        pointer-events: none;
        white-space: nowrap;
        animation: dormantFloat 6s ease-in-out infinite;
      }
      @keyframes dormantFloat {
        0%, 100% { transform: translateX(-50%) translateY(0); }
        50% { transform: translateX(-50%) translateY(-4px); }
      }

      .neural-detail-section {
        margin-bottom: 14px;
      }
      .neural-detail-label {
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        opacity: 0.4;
        margin-bottom: 6px;
      }
      .neural-detail-conv {
        font-size: 13px;
        line-height: 1.4;
        opacity: 0.75;
      }
      .neural-detail-meta {
        display: flex;
        gap: 12px;
        font-size: 12px;
        font-weight: 600;
      }
      .neural-detail-meta span {
        padding: 3px 8px;
        border-radius: 6px;
        background: rgba(255,255,255,0.05);
      }
      [data-theme="light"] .neural-detail-meta span,
      :root:not([data-theme="dark"]) .neural-detail-meta span {
        background: rgba(0,0,0,0.04);
      }
      .neural-detail-timeline {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .neural-detail-tool {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        opacity: 0.7;
      }
      .neural-detail-tool-dot {
        width: 6px; height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
      }
      .neural-detail-close {
        display: block;
        margin: 12px auto 0;
        padding: 4px 16px;
        border-radius: 8px;
        border: 1px solid rgba(255,255,255,0.1);
        background: transparent;
        color: inherit;
        font-size: 11px;
        font-weight: 600;
        opacity: 0.4;
        cursor: pointer;
        transition: opacity 0.2s;
      }
      .neural-detail-close:hover { opacity: 0.8; }
      [data-theme="light"] .neural-detail-close,
      :root:not([data-theme="dark"]) .neural-detail-close {
        border-color: rgba(0,0,0,0.1);
      }
    `})}export{ae as AgentDashboardView};
