"""Retry only omitted concepts with the existing Lemma prompt, repairs, and gates."""
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lemma import generate, lesson as L, factcheck
from lemma.claude import ClaudeProvider
from build_gallery import RUN, AUDIENCE, RecordingJob, save

key=subprocess.run(['pbpaste'],capture_output=True,text=True,check=True).stdout.strip()
if not key.startswith('sk-ant-') or any(c.isspace() for c in key):
    raise SystemExit('Clipboard key unavailable; nothing displayed.')
provider=ClaudeProvider(key)
for slug in ('brown-1954','euclid-equilateral'):
    folder=RUN/slug
    record=json.loads((folder/'build.json').read_text())
    if record['status']=='done': continue
    lesson=json.loads((folder/'lesson.json').read_text())
    outline=json.loads((folder/'outline.json').read_text())
    text=(folder/'source.txt').read_text()
    ready={c['id']:c for c in lesson['concepts']}
    job=RecordingJob()
    for c in outline['concepts']:
        if c['id'] in ready: continue
        base=ready.get(c.get('builds_on'))
        extra=''
        if base:
            extra='\nReuse the earlier model exactly, keeping every control id, label and range, adding at most one control. Earlier model:\n'+json.dumps(base['model'],ensure_ascii=False)
        if c==outline['concepts'][-1]: extra+='\nEnd on the lesson aha: '+outline['aha']
        extra+='\nA previous attempt failed: '+next((o['reason'] for o in lesson['omitted'] if o['title']==c['title']),'validation')
        task=generate.CONCEPT_TASK.format(audience=AUDIENCE,outline=generate._outline_text(outline['concepts'],c['id']),title=c['title'],id=c['id'],idea=c['idea'],visual=c['visual'],check_rule='Include one check.' if c.get('hard') else 'Do not include a check key.',extra=extra)
        def check(obj):
            if isinstance(obj,dict):
                obj['id']=c['id']
                if not c.get('hard'):obj.pop('check',None)
                obj.pop('builds_on',None)
                if base:obj['builds_on']=base['id']
            errors=list(L.check_concept(obj,L.normalize_for_match(text),'concept'))
            if base and not errors:errors+=list(L.check_builds_on(obj,base,'concept'))
            if not errors:errors+=factcheck.check_concept(obj,text,outline['concepts'].index(c)+1)
            return errors
        print(slug+': retrying '+c['id']+' with original generation task',flush=True)
        obj,errors=generate._ask_json(job,provider,generate.paper_document(text),task,check,c['id'])
        if errors:
            print(slug+': failed validation: '+str(errors[0]),flush=True)
            continue
        ready[c['id']]=obj
    lesson['concepts']=[ready[c['id']] for c in outline['concepts'] if c['id'] in ready]
    lesson['omitted']=[o for o in lesson['omitted'] if not any(c['title']==o['title'] for c in lesson['concepts'])]
    errors=list(L.check_lesson(lesson,text))
    if errors:raise SystemExit(slug+': final validation failed: '+errors[0])
    save(folder/'lesson.json',lesson)
    record.update(status='incomplete' if lesson['omitted'] else 'done',omitted=lesson['omitted'],concepts=len(lesson['concepts']),retry_repairs=getattr(job,'repairs',{}))
    save(folder/'build.json',record)
    print(slug+': '+record['status'],flush=True)
