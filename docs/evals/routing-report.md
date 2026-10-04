# Routing evaluation

Router model: `llama3.1-8b`. 44/47 passed (94%); hard cases 9/10.

| Route | Passed |
| --- | --- |
| lookup | 7/7 |
| analyst | 3/4 |
| knowledge | 4/4 |
| safety | 6/6 |
| action | 4/5 |
| refuse | 7/8 |
| panel | 13/13 |

## Failures

- `How much was approved on her claims this year?` expected ['analyst'], got ['lookup']
- `Pin that evidence` expected ['action'], got ['safety']
- `?` expected ['refuse'], got ['lookup']

## Confusion pairs

- analyst -> lookup: 1
- action -> safety: 1
- refuse -> lookup: 1
