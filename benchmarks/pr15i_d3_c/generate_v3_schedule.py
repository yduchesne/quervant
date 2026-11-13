#!/usr/bin/env python3
import json, random
AA_BASE=[["A","A","B","B"],["A","B","A","B"],["A","B","B","A"],["B","A","A","B"],["B","A","B","A"],["B","B","A","A"]]
FOUR_BASE=[["A","L","P","H","H","P","L","A"],["L","P","H","A","A","H","P","L"],["P","H","A","L","L","A","H","P"],["H","A","L","P","P","L","A","H"]]
ARMS=["A","L","P","H"]
def aa():
 r=random.Random(0xD3C30001); b=[row.copy() for row in AA_BASE for _ in range(2)]; r.shuffle(b); return b
def four(seed):
 r=random.Random(seed); blocks=[]
 for _ in range(3):
  renamed=ARMS.copy(); r.shuffle(renamed); rename=dict(zip(ARMS,renamed)); pos=list(range(8)); r.shuffle(pos)
  for row in FOUR_BASE:
   out=[None]*8
   for i,arm in enumerate(row): out[pos[i]]=rename[arm]
   blocks.append(out)
 r.shuffle(blocks); return blocks
if __name__=="__main__":
 print(json.dumps({"control_order":aa(),"campaign_01_order":four(0xD3C30011),"campaign_02_order":four(0xD3C30012)},sort_keys=True))
