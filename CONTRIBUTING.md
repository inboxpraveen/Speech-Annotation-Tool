# Contributing

Bug reports and pull requests are welcome.

## Reporting a problem

Open an issue with the operating system, how you run the app (Conda or Docker), the engine and model involved, what you did, what happened, and the relevant lines from `data/logs/app.log` or the job log. Screenshots help for interface problems.

## Working on the code

```bash
conda env create -f environment.yml
conda activate speech-annotation-tool
pip install pytest pyflakes
python app.py --dev
pytest -q
pyflakes sat
```

Keep changes small and focused. Match the style of the surrounding code. Add or adjust a test when you touch scanning, jobs, the review API or import/export. Update the documentation in `docs/` when behaviour changes.

Adding a speech provider or engine is described in [docs/development.md](docs/development.md).

## Pull requests

Branch from `master`, describe what the change does and why, and mention how you tested it. One topic per pull request.
