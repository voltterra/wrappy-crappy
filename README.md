# Wrappy Crappy to make your Agent CLI-Happy

No, seriously!

## Original thought

I had so many aha moment only to see after few months how people implement them.
It's a philosophical question of course whom ideas belong to [The essay "der Gedanke" by Gottlob Frege](https://en.wikipedia.org/wiki/Gottlob_Frege)). But, hey, who reads the books nowadays?

Enough with the introduction. I wanted to make my agents a bit more efficient and started exploring CLIs as an interface option.
Everyone knows that claude and co come equipped with great tools like, surprise! `bash`.
So instead of pounding json in "Figaro qua, Figaro là, Figaro su, Figaro giù." style to your agent, we could just use _existing_ cli tools an call them directly with subcommands and arguments.
Wasn't it a Unix design back then? Nevermind.
Then the news come that Google had released new agent first `googleworkspace` cli tool... So I recalled Frege once again, sweep(flip) the table clear and started writing this tool.

We shall see where it ends, but at least I'm happy I can show The world the `wrappy crappy` :)

## Author's Introduction

The tool is aimed to solve two unrelated yet surprisingly related goals:

1. Improve CLIs tool calls efficiency and robustness.
2. Create a security perimeter and controls for CLIs.
3. Optimize token counts and reduce context-window bloating.

How are we going to achieve both? All the favorites you despise and love:

1. Security over obscurity (it works surprisingly well here)
2. Spawning shell subprocesses in python (yikes)
3. Brittle CLI help pages parsing (there will be one on the Internet who will be doing it anyway)
4. Yamls everywhere
5. To spice it up - probably a skill.md to ducktape and blackbox all of the above.
   Nobody should know how we got there ;)

> Note: After this point, many content was generated with the help of ChatGPT or alike.
> I did my best to fact check and proofread, but the latter is my weakest point.

## Introduction

## Disclaimer

It may well be that all of the above have already been implemented. "But hey, who reads books nowadays?"
