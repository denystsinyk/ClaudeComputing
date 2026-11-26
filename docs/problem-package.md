# Problem package v1

Each prebuilt problem lives in `examples/<id>/`. `examples/task-store/` is the first package and a template for future Python problems. The `manifest.json` at the package root has a `schema_version` so later package changes can be handled explicitly.

| Manifest field | Meaning |
| --- | --- |
| `id`, `title`, `language`, `difficulty`, `estimated_minutes` | Catalog metadata. |
| `instructions` | Markdown shown to the solver. |
| `starter_files` | Editable files sent to the browser; paths are relative to the package root. Their `starter/` prefix is removed in the solver workspace. |
| `visible_tests` | Pytest files the solver can see and run. |
| `hidden_tests` | Private pytest files used only for submission. |
| `reference_files` | Private mapping from a starter path to its known-good replacement. This is for fixture checks, not for solver jobs. |

The manifest is **server-side metadata**. The API should construct a safe client response from the instructions, starter files, and visible tests; it must never return the manifest verbatim, hidden tests, or reference files. A future package loader must validate schema version, required fields, file types, and relative paths before loading generated packages or running code. Do not trust paths from a generated manifest.

To verify the fixture locally, copy the starter files into a temporary workspace, replace `task_store.py` with `reference/task_store.py`, and run both test files with pytest. Run the visible tests against the unmodified starter to check that the exercise is unsolved. This fixture check uses trusted repository code; submitted user code belongs only in the isolated runner.
