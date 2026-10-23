# Demo

`ab-demo.sh` is a live A/B for a meetup: one question a tester asks about an
unfamiliar suite — "where is this step defined, and has someone already written
it twice?" — answered first by hand with `grep`, then by `where-are-we`.

```sh
docs/demo/ab-demo.sh              # on the bundled sample suite
docs/demo/ab-demo.sh /path/to/suite   # on your own behave/pytest suite
```

`sample-suite/` is a small behave suite with a planted duplicate: two authors
wrote the "payment captured" precondition slightly differently
(`the payment has been captured` vs `the payment has been fully captured`), and
a dead page-object method. Grep sees five scattered hits; the map names the
definition and reports the overlap with a similarity score.
