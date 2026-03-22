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

We shall see where it ends, but at least I'm happy I can reveal to the World the `wrappy-crappy` project 💁

## Description

The tool is aimed to solve two unrelated yet surprisingly related goals:

1. Improve CLIs tool calls efficiency and robustness.
2. Create a security perimeter and controls for general purpose CLIs.
3. Optimize token counts and reduce context-window bloating.

How are we going to achieve both? With all the favorites we despise and love:

1. Security over obscurity (it works surprisingly well here)
2. Spawning shell subprocesses in python (yikes)
3. Brittle CLI help pages parsing (there will be one on the Internet who will be doing it anyway)
4. Yamls everywhere
5. To spice it up - probably a skill.md to ducktape and blackbox all of the above.
   Nobody should know how we got there ;)
6. Dangerously skipping code inspection, architecture, measures to reduce blast radius;
7. Garbage in -> garbage out. You spend one evening writing a CLI, the crappy will "wrappy" it in seconds to make you happy!

## Installation

```bash
# From source (requires uv or pip)
git clone https://github.com/your-repo/wrappy-crappy.git
cd wrappy-crappy
pip install .

# Or with uv
uv pip install .
```

## Usage

```bash
# Show the tool interface tree
crpy interface <tool.yaml>

# Show the tool interface with scope restrictions
crpy interface <tool.yaml> --scope <scope.yaml>

# Show TypeScript schema for a command group
crpy schema <tool.yaml> <group>

# Show schema for a specific command
crpy schema <tool.yaml> <group> <command>

# Execute a wrapped command with scope enforcement
crpy exec <tool.yaml> --scope <scope.yaml> <group> <command> --params '{"key": "value"}'
```

## Introduction

The tool traverses the target CLI built-in help and try to discover all possible paths to commands, command groups, subcommands, arguments, flags/parameters.
It is not a reliable process (hence the thoughts about SKILLS.MD). Each tool has a unique help structure that may not generalize well to other tools' help pages.

The output of this process is a tree-like structure stored in yaml. It will be later used to generate the target CLI help pages on the fly in a desired supported format.

- Target Formats include(not all of them are available):
  - Tree of command groups with subcommands; args details as Typescript Interface
  - TODO: Tree of command groups with subcommands; args details as Python Interface
  - TODO: Original + discovery and security constrains
  - TODO: JSON + discovery and security constrains

> Reminder: My original thought was "There are 3 help page formats supported: original (keep everything, remove disabled tools), json (take whatever is possible, represent it as json, remove disabled tools), tree, tree + typescript, tree + python"

### Process

The tool has a discovery mode as a separate half-way backed script. I had only run it once before it broke, so you should trust me it was functional.
Example after "broken discovery" (available at `examples/crpy_mock_devops/devops-tool`):

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

After calling `crpy interface examples/crpy_mock_devops/devops-tool.yaml`, the tool produces a tree of all available commands:

```bash
devops v0.3.0 — DevOps platform CLI — deploy, monitor, manage

devops/
├── deploy/                 Manage deployments and releases
│   ├── create
│   ├── rollback
│   ├── list
│   ├── promote
│   └── destroy
├── secrets/                Manage secrets and credentials
│   ├── set
│   ├── get
│   ├── list
│   ├── rotate
│   └── delete
└── monitor/                Monitoring, alerts, and observability
    ├── status
    ├── logs
    ├── alert
    └── metrics

Use: crpy schema <tool> <group> for TypeScript interfaces
```

Let's scope it with `crpy interface examples/crpy_mock_devops/devops-tool.yaml --scope examples/crpy_mock_devops/agent-scope.yaml`
The outcome changes slightly:

```bash
devops v0.3.0 — DevOps platform CLI — deploy, monitor, manage

devops/
├── deploy/                 Manage deployments and releases
│   ├── create
│   ├── list
│   └── promote
├── secrets/                Manage secrets and credentials
│   └── list
└── monitor/                Monitoring, alerts, and observability
    ├── status
    ├── logs
    ├── alert
    └── metrics

Use: crpy schema <tool> <group> for TypeScript interfaces
```

And when we drill down with `crpy schema examples/crpy_mock_devops/devops-tool.yaml deploy --scope examples/crpy_mock_devops/agent-scope.yaml`

```bash
// devops deploy — Manage deployments and releases

// devops deploy create — Create a new deployment
interface CreateInput {
  service: string;  // Service name
  image: string;  // Container image:tag
  env?: string;  // FIXED: staging
  replicas?: number;  // FIXED: 2
  cpu?: string;  // FIXED: 250m
  memory?: string;  // FIXED: 256Mi
  timeout?: number;  // Rollout timeout seconds
  dry_run?: boolean;  // Preview without applying
}
interface CreateOutput {
  deployment_id: string;  // Created deployment ID
  status: string;  // Deployment status
  url: string;  // Service endpoint URL
  replicas_ready: number;  // Ready replica count
}

// devops deploy list — List deployments for a service
interface ListInput {
  service?: string;  // Service name
  env?: "staging" | "production" | "canary";  // Filter by environment
  status?: "running" | "failed" | "pending";  // Filter by status
  limit?: number;  // Max results
}
interface ListOutput {
  deployments: any[];  // Array of deployment objects
  total: number;  // Total deployments found
}

// devops deploy promote — Promote deployment from staging to production
interface PromoteInput {
  deployment_id: string;  // Staging deployment ID
  canary_pct?: number;  // FIXED: 5
  auto_promote?: boolean;  // Auto-promote after health check
}
interface PromoteOutput {
  production_id: string;  // Production deployment ID
  canary_status: string;  // Canary health status
}
```

### Outcome

What is achieved

1. Scoped tools exposure - smaller context window for tool discovery.
2. When an agent needs to uncover more details, it descents to `deploy` schema.
3. The schema itself is rendered as TypeScript interfaces (not structured very intelligently though. Will be fixed).
4. "FIXED" parameters are frozen. An agent won't be able to change them and delete all your google drive files, or start deleting all your emails.
5. Once `crpy` reaches some maturity, this will be one time operation to create a fixed "wrapper" - think a command a la `crpy-devops`, `crpy-openclaw`, `crpy-gws` or whichever CLI you want to expose to an agent.

### Where it could go

1. Maybe it will converge to an MCP-like interface code generation tool, so your agent will end up importing "scoped" CLI-backed libraries.
2. Claude doesn't need mcp_discovery tool with embeddings, regex and BM25 lookups?

### More examples

#### Proper tool: podman

Let crpy work on non-crappy tools: `crpy interface examples/crpy_podman/podman.yaml`

```bash
podman v5.8.0 — Manage pods, containers and images

podman/
...
├── _global/                Global flags available on all commands
├── compose/                Run compose workloads via an external provider such as docker-compose or podman-compose
│   ├── attach
│   ├── build
│   ├── commit
│   ├── config
│   ├── cp
│   ├── create
│   ├── down
│   ├── events
│   ├── exec
│   ├── export
│   ├── images
│   ├── kill
│   ├── logs
│   ├── ls
│   ├── pause
...
```

Make it scoped for the task `crpy interface examples/crpy_podman/podman.yaml --scope examples/crpy_podman/podman-scoped-example.yaml`

```bash
podman v5.8.0 — Manage pods, containers and images

podman/
├── _global/                Global flags available on all commands
│   └── _flags
└── container/              Manage containers
    ├── diff
    ├── exists
    ├── inspect
    ├── list
    ├── logs
    ├── port
    ├── ps
    ├── stats
    └── top

Use: crpy schema <tool> <group> for TypeScript interfaces
```

And the schema discovery `crpy schema examples/crpy_podman/podman.yaml container --scope examples/crpy_podman/podman-scoped-example.yaml`

```bash

// podman container — Manage containers

// podman container diff — Inspect changes to the container's file systems
interface DiffInput {
  format?: string;  // Change the output format (json)
}

// podman container exists — Check if a container exists in local storage
interface ExistsInput {
  external?: boolean;  // Check external storage containers as well as Podman containers
}

// podman container inspect — Display the configuration of a container
interface InspectInput {
  format?: string;  // FIXED: json
  size?: boolean;  // Display total file size
}
...
```

## Important

> Note: After this point, many content was generated with the help of ChatGPT or alike.
> I did my best to fact check and proofread, but the latter is my weakest point.

## Final thoughts

It may well be that all of the above has already been implemented. "But hey, who reads books nowadays?"

I might need a good name suggestion 😂

I guess, happy wrapping everyone 🫶
