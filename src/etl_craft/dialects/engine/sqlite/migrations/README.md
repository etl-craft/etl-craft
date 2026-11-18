# Engine DB migrations

`etl-craft migrate` applies the files in this directory to an existing Engine DB, as the
`ENGINE` stream, before a deployment's own `PROJECT` stream. `../schema.sql` is the 0.9.0
baseline a new Engine DB starts from; `init-db` records it as `baseline-0.9.0`. Before 0.9.0 is
tagged, Engine DB changes edit the baseline directly and this directory stays empty; from then
on every change is a new file here.

- One file per change, `NNNN_short_description.sql`, applied in filename order.
- Every change is made in `../schema.sql` as well, so a new install and a migrated one end up
  the same.
- A file is never edited once released: `migrate` records its SHA-256 and refuses one that
  changed.
