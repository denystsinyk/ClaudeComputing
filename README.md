# CS 1660 | Cloud Computing

## Claude Computing

### SudoSolver repository structure

```text
.
├── frontend/              # React + TypeScript + Monaco
├── backend/               # Python API + authentication + data
├── services/              # Independent workers
│   ├── generator/         # LLM providers + validation
│   └── runner/            # Dockerized pytest execution
├── infra/                 # Terraform AWS resources
├── examples/              # Prebuilt interview problems
├── docs/                  # Architecture + API contracts
├── .github/
│   └── workflows/         # CI/CD automation
└── Makefile               # Common development commands
```

Most component directories currently contain `.gitkeep` placeholders. The first
prebuilt exercise is in [`examples/task-store/`](examples/task-store/), with its
package layout described in [`docs/problem-package.md`](docs/problem-package.md).
Run `make help` to see the available development commands.
