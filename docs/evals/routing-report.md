# Routing evaluation

Router model: `llama3.1-8b`. 30/35 passed (86%); hard cases 8/10.

| Route | Passed |
| --- | --- |
| lookup | 6/7 |
| analyst | 2/4 |
| knowledge | 4/4 |
| safety | 6/6 |
| action | 4/5 |
| refuse | 8/9 |

## Failures

- `Which medicines were started in the last six months?` expected ['analyst'], got ['lookup']
- `How much was approved on her claims this year?` expected ['analyst'], got ['lookup']
- `Pin that evidence` expected ['action'], got ['safety']
- `what about that one?` expected ['lookup'], got ['refuse']
- `?` expected ['refuse'], got ['lookup']

## Confusion pairs

- analyst -> lookup: 2
- action -> safety: 1
- lookup -> refuse: 1
- refuse -> lookup: 1
