# Release instructions

The first public release is **alpha**. Limitations in the README still apply.

## Checklist

1. `make check` and `make test` are green locally.
2. CI is green on macOS and Ubuntu for Python 3.12 and 3.13.
3. `make audit` and `make package` succeed.
4. Compatibility matrix rows you claim are filled with synthetic results.
5. Changelog version and `__version__` match the tag (`v0.1.0`).
6. Tag `v0.1.0` or run the Release workflow manually. After a GitHub Environment
   named `release` exists (Settings → Environments), you can point these jobs at
   it with `environment: release` for reviewer gates and signing secrets.
7. Attach SHA-256 checksums, SBOM, and provenance attestations from the workflow.
8. Keep the GitHub release in **draft** until notes and assets are reviewed.
9. Do not enable Windows as a supported platform.

## Signing

Checksums and GitHub attestations are produced automatically. Apple notarisation
and a signed Linux package need credentials in the `release` environment
(`MACOS_SIGNING_IDENTITY` and related secrets). Until those exist, ship the
wheel/sdist as the portable artifact and label the GUI unsigned.

## PyPI

Publishing to PyPI is optional for the alpha. If you publish, use trusted
publishing (OIDC) rather than a long-lived token.
