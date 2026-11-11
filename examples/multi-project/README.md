# Multiple projects

With the package installed and a configured Engine DB:

```bash
python examples/multi-project/ten_projects.py examples/demo/craft-connector.yml
```

The script creates ten isolated project folders and runs one Python task per
project through the CLI, sharing the configured Engine DB. It preserves existing
project metadata. Each project writes its own one-row target.
