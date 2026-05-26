# greeter-project

A tiny project that ships an in-repo lola module under `.lola/modules/greeter`
providing a `greet` skill. Used by lola-eval to validate Mode-1 (project)
auto-scaffolding: the harness scaffolds the in-repo module into the agent's
config so the `/greet` skill is discoverable.
