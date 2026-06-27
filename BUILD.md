# Build Notes

This repository uses `setuptools` with a `src/` layout.

## Wheel

```bash
python -m pip install build
python -m build
```

## Editable development install

```bash
python -m pip install -e .
```

## Arch packaging

Use the template in `packaging/PKGBUILD` as the basis for a local package.

