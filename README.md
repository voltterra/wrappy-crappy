# Wrappy Crappy to make your Agent CLI-Happy

No, seriously!

## Idea's Origin

I have been having so many `💡` moments only to see after few months how people implement them (sometimes poorly).
It's a philosophical question of course whom ideas belong to [The essay "der Gedanke" by Gottlob Frege](https://en.wikipedia.org/wiki/Gottlob_Frege)). But, hey, who reads books nowadays?

Enough with the introduction. I wanted to make my agents a bit more efficient and started exploring CLIs as an interface option.
Everyone knows that **claude** and co come equipped with great tools like, surprise! - `bash`.
So instead of pounding json in "Figaro qua, Figaro là, Figaro su, Figaro giù." style to your agent, we could just use _existing_ cli tools an call them directly with subcommands and arguments.
Wasn't it a corner stone of UNIX philosophy?

Then the news come that Google had released new agent first `googleworkspace` cli tool... So I recalled Frege once again, sweep(flip) the table clear and started writing this tool.

We shall see where it ends, but at least I'm happy I can reveal to the World the `wrappy crappy` project 💁

## Author's Introduction

The tool is aimed to solve two unrelated yet surprisingly related goals:

1. Improve CLIs tool calls efficiency and robustness.
2. Create a security perimeter and controls for general purpose CLIs.
3. Optimize token counts and reduce context-window bloating.

How are we going to achieve both? All the favorites we despise and love:

1. Security over obscurity (it works surprisingly well here)
2. Spawning shell subprocesses in python (yikes)
3. Brittle CLI help pages parsing (there will be one on the Internet who will be doing it anyway)
4. Yamls everywhere
5. To spice it up - probably a skill.md to ducktape and blackbox all of the above.
   Nobody should know how we got there ;)
6. Dangerously skipping code inspection, architecture, measures to reduce blast radius;
7. Garbage in -> garbage out. You spend one evening writing a CLI, the crappy will "wrappy" it

> Note: After this point, many content was generated with the help of ChatGPT or alike.
> I did my best to fact check and proofread, but the latter is my weakest point.

## Introduction

The tool traverses the target CLI built-in help and try to discover all possible paths to commands, command groups, subcommands, arguments, flags/parameters.
It is not a reliable process (hence the thoughts about SKILLS.MD). Each tool has a unique help structure that may not generalize well to other tools' help pages.

The output of this process is a tree-like structure stored in yaml. It will be later used to generate the target CLI help pages on the fly in supported formats.

Example (available at `examples/crpy_mock_devops/devops-tool`):

```yaml
groups:
  - name: deploy
    description: "Manage deployments and releases"
    commands:
      - name: create
        description: "Create a new deployment"
        params:
          - {
              name: service,
              type: STR,
              description: "Service name",
              required: true,
            }
        outputs:
          - {
              name: deployment_id,
              type: STR,
              description: "Created deployment ID",
            }
```

- Target Formats include(not all of them are available):
  - Tree of command groups with subcommands; args details as Typescript Interface
  - TODO: Tree of command groups with subcommands; args details as Python Interface
  - TODO: Original + discovery and security constrains
  - TODO: JSON + discovery and security constrains

> Reminder: My original thought was "There are 3 help page formats supported: original (keep everything, remove disabled tools), json (take whatever is possible, represent it as json, remove disabled tools), tree, tree + typescript, tree + python"

## Disclaimer

It may well be that all of the above have already been implemented. "But hey, who reads books nowadays?"

I might need a good name suggestion 😂
