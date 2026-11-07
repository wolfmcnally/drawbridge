---
title: Give parallel tests independent self-provisioning script caches
scope: methodology
proposed_surface: bin
source: learn
slug: merciful-aardwolf
status: candidate
filed: '2026-11-07'
occurrences:
- date: '2026-11-07'
  ref: Canonical receiving full-gate failure and seven-case parallel/serial controls
---

Assign independently mutable standalone-script caches to their actual test workers when isolating parallel test HOME. The live gate observed missing PyYAML/ruamel submodules and an environment-directory deletion conflict in a shared uv script cache. Seven affected cases reproduced failures in parallel, passed serially, and passed in parallel with worker-owned caches. This establishes a sufficient correction at the ownership boundary; the evidence does not distinguish all contributions of filesystem location and interpreter selection. Keep parallel execution, runtime selection and all original assertions intact. Do not infer that a warmed isolated qualification covers a cold live cache.