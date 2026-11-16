# Extensions

Models, unit hydrographs, losses, objectives and solvers registered with sparsehydro appear in the viewer without
any change to it: the Model page offers the unit hydrographs and losses, Calibrate the objectives and optimizers.

## Installed packages

A package declares its registration module in the `sparsehydro.extensions` entry-point group:

```toml
[project.entry-points."sparsehydro.extensions"]
my_models = "my_package.sparsehydro_models"
```

Importing that module registers its classes (see sparsehydro's "Packaging an extension"). The viewer loads every
installed extension when it starts, through `sparsehydro.load_extensions()`.

## Modules and files

Modules or `.py` files can also be listed in the settings key `extensions/modules`, one per line. They are imported
at start-up in the same way.

## Failures

An extension that fails to import is reported in the log (Activity panel) and skipped; the application starts
normally. `sparsehydro-viewer --self-test report.txt` lists the extensions loaded and fails if one of them cannot be
imported.
