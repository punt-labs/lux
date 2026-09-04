# Target Architecture Docs

These documents describe the architecture Lux is being rewritten toward.

- [target.md](./target.md): canonical target summary
- [topology.md](./topology.md): process roles, replication, deployment
- [ui-model.md](./ui-model.md): authoritative UI object model
- [element-contract.md](./element-contract.md): draft normative Element contract
- [introspection-api.md](./introspection-api.md): verification surface

The identity ladder, multi-Hub aggregation, and cross-host transport and
trust model (DES-089, DES-090) are specified in
[system.tex](../system.tex) §"Identity, Addressing, and Multi-Hub
Topology" and §"Cross-Host Transport and Trust" — operator direction
(2026-09-04) folds architecture designs into `system.tex` rather than a
standalone target markdown once a design is evaluator-accepted. The
implementation plan for both is
[multi-hub-addressing-work.md](../multi-hub-addressing-work.md). The
original design drafts are archived at
[../archive/addressing.md](../archive/addressing.md) and
[../archive/cross-host-transport.md](../archive/cross-host-transport.md).

For the current/intermediate implementation, use [system.tex](../system.tex).
