#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,collections,datetime,csv
ROOT=Path(__file__).resolve().parents[2]
D=ROOT/'data/releases/qwen3_fashion_664_v1_1'
def read(n):return [json.loads(x) for x in (D/n).read_text(encoding='utf-8').splitlines() if x.strip()]
def main():
    meta=json.loads((D/'manifest.json').read_text(encoding='utf-8'))
    for n,h in meta['files_sha256'].items():
      assert hashlib.sha256((D/n).read_bytes()).hexdigest()==h,(n,'SHA256 불일치')
    rows,val,test,prov=(read(x) for x in ('train.jsonl','validation.jsonl','test.jsonl','train_provenance.jsonl'))
    assert (len(rows),len(val),len(test),len(prov))==(664,8,8,664)
    assert collections.Counter(x['source'] for x in prov)=={'synthetic':600,'gold':64}
    assert collections.Counter(x['type'] for x in prov)=={'fashion_recommendation':415,'tool_calling':249}
    assert [x['line'] for x in prov]==list(range(1,665))
    assert len({x['id'] for x in prov})==664
    requests=[]
    for row,p in zip(rows,prov):
        assert set(row)=={'messages','tools'}
        msgs=row['messages'];assert msgs[0]['role']=='system' and msgs[1]['role']=='user' and msgs[-1]['role']=='assistant'
        req=msgs[1]['content'].split('사용자 요청: ',1)[-1].split('\ncontext:',1)[0].strip();requests.append(req)
        if p['type']=='fashion_recommendation':
          assert row['tools']==[]
          looks=json.loads(msgs[-1]['content'])['looks']
          assert len(looks)==5
          assert [a['role'] for a in looks]==['preference_best','preference_alternative','exploration','wardrobe_best','wardrobe_alternative']
          if p['source']=='synthetic':
            ctx=json.loads(msgs[1]['content'].split('\ncontext: ',1)[1]);wi={w['item_id']:w for w in ctx['wardrobe']}
            for k,look in enumerate(looks):
              if look['status']=='unavailable':assert look['items']==[];continue
              assert {'top','bottom','shoes'}<=set(it['slot'] for it in look['items'])
              for it in look['items']:
                 if k>=3:assert it['item_id'] in wi and wi[it['item_id']]['category']==it['slot']
                 else:assert it['item_id'] is None
        else:
          assert len(row['tools'])==4
          calls=[c for m in msgs for c in m.get('tool_calls',[])]
          ret=[m for m in msgs if m['role']=='tool']
          assert len(calls)==len(ret)
          for c,r in zip(calls,ret):
             assert c['id']==r['tool_call_id'] and c['function']['name']==r['name']
             assert isinstance(c['function']['arguments'],dict)
             json.loads(r['content'])
          json.loads(msgs[-1]['content'])
    assert len(requests)==len(set(requests))
    held=[x['messages'][1]['content'].split('사용자 요청: ',1)[-1].split('\ncontext:',1)[0].strip() for x in val+test]
    assert not set(requests)&set(held)
    print('PASS: SHA256, 664/8/8, 64 Gold + 600 Synthetic, FR/TC, JSON schema, tool calls, wardrobe IDs, exact request overlap')
    with (D/'priority_review_57.csv').open(encoding='utf-8-sig',newline='') as f:
        approved=list(csv.DictReader(f))
    assert len(approved)==57 and len({r['id'] for r in approved})==57
    assert all(r['human_signoff']=='APPROVED' for r in approved)
    review=memo=meta['priority_review_57_human_signoff']
    assert (review['approved'],review['revision_needed'],review['deferred'])==(57,0,0)
    print('REVIEW: 57 priority records human-approved (32 FR / 25 TC), revision 0, deferred 0')
    print('CAVEAT: 전체 664건 전수 인간 검수 및 실제 Qwen3 채팅 템플릿 호환성 검증은 별도')
if __name__=='__main__':main()
