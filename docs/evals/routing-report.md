# Routing evaluation

Router model: `llama3.1-8b`. 72/73 passed (99%); hard cases 10/10.

| Route | Passed |
| --- | --- |
| lookup | 7/7 |
| analyst | 3/4 |
| knowledge | 5/5 |
| safety | 6/6 |
| action | 5/5 |
| refuse | 12/12 |
| panel | 14/14 |
| agent | 13/13 |
| propose | 7/7 |

## Failures

- `How much was approved on her claims this year?` expected ['analyst'], got ['lookup']

## Confusion pairs

- analyst -> lookup: 1
