# RedHat package fixtures

These RPMs are tiny noarch packages used by the phase coverage Molecule
scenarios on Rocky Linux 9. They are committed with static Yum repository
metadata so the tests can install real RPM package records without enabling
external repositories, downloading packages, or requiring `rpmbuild` inside the
Molecule image.

The fixtures provide only the package names, versions, and minimal files the
role needs during tests:

- `java-11-openjdk-11.0.0-1.noarch.rpm`
- `java-11-openjdk-devel-11.0.0-1.noarch.rpm`
- `elasticsearch-6.8.23-1.noarch.rpm`

The `repodata/` directory is generated from these fixtures with `createrepo_c`.
