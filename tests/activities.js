// Run with node tests/activities.js. Exercises real event handlers without a browser dependency.
const assert = require('node:assert/strict');
class Node {
  constructor(tag) { this.tagName=tag; this.children=[]; this.attrs={}; this.events={}; this.value=''; this.dataset={}; this.textContent=''; }
  setAttribute(k,v) { this.attrs[k]=String(v); }
  addEventListener(k,v) { this.events[k]=v; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
}
global.document={createElement:t=>new Node(t),createElementNS:(_,t)=>new Node(t),createTextNode:t=>({textContent:t})};
require('../lemma/static/activities.js');
function all(n,tag) { return [ ...(n.tagName===tag?[n]:[]),...n.children?.flatMap(c=>all(c,tag))||[] ]; }
function click(n) { assert.ok(n); n.events.click(); }
let covered=new Set();
const fixtures = [
 {kind:'sort',id:'board',title:'Connect evidence',prompt:'Classify the cards.',hints:['A claim concludes; evidence records.'],groups:[{id:'claim',label:'Claim'},{id:'evidence',label:'Evidence'}],cards:[{id:'a',text:'A claim',group:'claim',feedback:'This states a conclusion.'},{id:'b',text:'A record',group:'evidence',feedback:'This supplies evidence.'}],takeaway:'Distinguish the roles.'},
 {kind:'construction',id:'construct',title:'Construct a triangle',prompt:'Draw both circles.'},
 {kind:'inheritance',id:'cross',title:'Cross the peas',prompt:'Compare combinations and samples.'},
];
for(const activity of fixtures) {
  covered.add(activity.kind);
  const root=new Node('main'),state={};let completions=0;
  LemmaActivities.mount(root,activity,state,()=>completions++);
  if(activity.kind==='sort') {
   const selects=all(root,'select');assert.equal(selects.length,activity.cards.length);
   selects.forEach((s,i)=>{s.value=activity.cards[i].group;s.events.change();});
   click(all(root,'button')[0]);assert.equal(state.done,true);assert.equal(completions,1);
   selects[0].value='';selects[0].events.change();assert.equal(state.done,false);
   click(all(root,'button')[1]);assert.equal(state.hints,1);
   click(all(root,'button')[2]);assert.equal(state.done,true);
  } else if(activity.kind==='construction') {
   click(all(root,'button')[0]);click(all(root,'button')[1]);click(all(root,'button')[2]);
   assert.equal(state.joined,true);assert.equal(state.done,true);assert.equal(all(root,'path').length,1);
   click(all(root,'button')[3]);assert.equal(state.joined,false);
  } else {
   assert.equal(all(root,'button').filter(n=>n.className?.includes('inheritance-seed')).length,4);
   click(all(root,'button').at(-1));assert.equal(state.counts.round+state.counts.wrinkled,20);
   const select=all(root,'select')[0];select.value='AA';select.events.change();
   click(all(root,'button').at(-1));assert.equal(state.counts.wrinkled,0);assert.equal(state.counts.round,20);
  }
 }
assert.equal(covered.size,3);

// The model-free blocks: each is completed through its own handlers, after a wrong attempt where it can have one.
const byText=(root,text)=>all(root,'button').find(b=>b.children.some(c=>c.textContent===text)||b.textContent===text);
function mounted(activity,env={}) { const root=new Node('main'),state={};let completions=0; LemmaActivities.mount(root,activity,state,()=>completions++,env); covered.add(activity.kind); return {root,state,done:()=>completions}; }
{ // worked example: steps appear one at a time, then the takeaway
  const a={kind:'worked',id:'w',title:'Count a field',steps:[{text:'1000 hypotheses, 100 true.'},{text:'Power 0.8 finds 80.',result:'80 true positives'},{text:'Alpha 0.05 passes 45 false ones.'}],takeaway:'Most positives can still be true.'};
  const m=mounted(a);assert.equal(all(m.root,'li').length,1);
  click(byText(m.root,'Next step'));assert.equal(m.done(),0);click(all(m.root,'button')[0]);
  assert.equal(all(m.root,'li').length,3);assert.equal(m.state.done,true);assert.equal(m.done(),1); }
{ // staged evidence: one stage at a time
  const a={kind:'stages',id:'s',prompt:'Follow Smith.',stages:[{label:'His evidence',text:'Jones will get the job.'},{label:'The facts',text:'Smith gets the job.'}],takeaway:'Justified, true, yet lucky.'};
  const m=mounted(a);click(all(m.root,'button')[0]);assert.equal(m.state.done,true);assert.equal(all(m.root,'li').length,2); }
{ // comparison: text cases and live model states drawn by the player
  const drawn=[];const a={kind:'compare',id:'c',prompt:'Compare.',cases:[{label:'Open gates',values:{weld:0}},{label:'Welded',text:'Nobody leaves.'}],takeaway:'The wall cuts both ways.'};
  const m=mounted(a,{renderModel:(box,values)=>drawn.push(values)});assert.deepEqual(drawn,[{weld:0}]);
  click(all(m.root,'button')[0]);assert.equal(m.state.done,true); }
{ // matching: wrong first, then one to one
  const a={kind:'match',id:'m',prompt:'Match.',pairs:[{id:'a',text:'CA = AB',target:'Radii of circle A',feedback:'Both are radii.'},{id:'b',text:'CB = AB',target:'Radii of circle B',feedback:'Both are radii.'},{id:'c',text:'CA = CB',target:'Common notion 1',feedback:'Equal to the same thing.'}],takeaway:'Each equality has a reason.',hints:['Which circle is C on?']};
  const m=mounted(a);const selects=all(m.root,'select');
  selects.forEach(s=>{s.value=a.pairs[0].target;s.events.change();});click(byText(m.root,'Check matches'));assert.equal(m.done(),0);
  click(byText(m.root,'Hint'));assert.equal(m.state.hints,1);assert.equal(all(m.root,'li').length,1);
  selects.forEach((s,i)=>{s.value=a.pairs[i].target;s.events.change();});click(byText(m.root,'Check matches'));assert.equal(m.done(),1); }
{ // ordering: shuffled, a wrong check, then Show me puts it right
  const a={kind:'order',id:'o',prompt:'Order the chain.',items:['Separation','Feeling inferior','Less motivation','Slower learning'],explanation:'Each link causes the next.'};
  const m=mounted(a);assert.notDeepEqual(m.state.order,a.items);click(byText(m.root,'Check order'));assert.equal(m.done(),0);
  click(byText(m.root,'Show me'));assert.deepEqual(m.state.order,a.items);assert.equal(m.done(),1); }
{ // tracing: pick a path along the links, by click and by keyboard
  const a={kind:'trace',id:'t',prompt:'Trace word 1 to word 4.',path:true,nodes:[{id:'w1',label:'1',x:10,y:50},{id:'w2',label:'2',x:40,y:50},{id:'w4',label:'4',x:90,y:50}],edges:[{from:'w1',to:'w2'},{from:'w2',to:'w4'}],answer:['w1','w2','w4'],explanation:'Each step is one link.'};
  const m=mounted(a);const node=i=>all(m.root,'g')[i];
  click(node(2));click(byText(m.root,'Check'));assert.equal(m.done(),0);
  click(byText(m.root,'Clear'));node(0).events.click();node(1).events.keydown({key:'Enter'});node(2).events.click();
  assert.deepEqual(m.state.picked,['w1','w2','w4']);click(byText(m.root,'Check'));assert.equal(m.done(),1); }
{ // supporting passage
  const a={kind:'passage',id:'p',question:'Which passage supports it?',answer:1,options:[{quote:'one two three four five six',feedback:'Related, but not the claim.'},{quote:'seven eight nine ten eleven twelve',source_id:'s2',feedback:'This states it.'}]};
  const m=mounted(a,{sourceTitle:id=>'Source '+id});const radios=all(m.root,'input');
  radios[0].events.change();click(byText(m.root,'Check'));assert.equal(m.done(),0);
  radios[1].events.change();click(byText(m.root,'Check'));assert.equal(m.done(),1); }
{ // numeric estimate within a tolerance
  const a={kind:'estimate',id:'e',question:'How many false positives?',answer:45,tolerance:5,explanation:'5% of 900.'};
  const m=mounted(a);const input=all(m.root,'input')[0];
  input.value='80';input.events.input();click(byText(m.root,'Check'));assert.equal(m.done(),0);
  input.value='47';input.events.input();click(byText(m.root,'Check'));assert.equal(m.done(),1); }
{ // a construction from authored steps, in order
  const a={kind:'construction',id:'k',title:'Bisect',prompt:'Build it.',steps:[{label:'Circle at A',note:'Radius AB.',shapes:[{type:'circle',x:30,y:50,r:40}]},{label:'Join',note:'Done.',shapes:[{type:'line',x1:30,y1:50,x2:70,y2:50},{type:'point',x:70,y:50,label:'B'}]}],takeaway:'Every step is justified.'};
  const m=mounted(a);const steps=all(m.root,'button');assert.ok('disabled' in steps[1].attrs);
  click(steps[0]);click(all(m.root,'button')[1]);assert.equal(m.done(),1);assert.equal(all(m.root,'line').length,1); }
{ // a cross with a chosen second parent
  const m=mounted({kind:'inheritance',id:'x',title:'Backcross',prompt:'Cross with a pure recessive.',parent:'Aa',second:'aa'});
  click(all(m.root,'button').at(-1));assert.ok(m.state.counts.wrinkled>0||m.state.counts.round>0);
  assert.equal(all(m.root,'button').filter(n=>n.className?.includes('wrinkled')).length,2); }
assert.equal(covered.size,LemmaActivities.KINDS.length);
console.log('Interactive teaching activity fixtures passed.');
