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
 {kind:'sort',id:'board',title:'Connect evidence',prompt:'Classify the cards.',groups:[{id:'claim',label:'Claim'},{id:'evidence',label:'Evidence'}],cards:[{id:'a',text:'A claim',group:'claim',feedback:'This states a conclusion.'},{id:'b',text:'A record',group:'evidence',feedback:'This supplies evidence.'}],takeaway:'Distinguish the roles.'},
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
   click(all(root,'button')[1]);assert.equal(state.done,true);
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
console.log('Interactive teaching activity fixtures passed.');
