# CROCO Experiment Builder

## What this is (and what it is not)

**CROCO Experiment Builder** is a lightweight framework to *design, build, and run CROCO experiments in a reproducible and controlled way*, without modifying the CROCO source tree itself.

It is **not** a new ocean model, nor a wrapper that hides CROCO. On the contrary:

> CROCO is best understood as a **highly structured scientific code library**.
> 
> A “CROCO model” only exists *after* a research team selects a set of compile-time directives, parameter files, and workflows that together define a specific experiment.

This repository exists to make that process **explicit, reproducible, and debuggable**.

---

## Core idea

- The CROCO *distribution* is treated as **read-only**.
- Every experiment is **self-contained**:
  - its own configuration
  - its own compilation
  - its own runtime
- The experiment, not the model, is the atomic research object.

If you have ever wondered *"which CROCO did we actually run for this paper?"*, this framework is meant for you.

---

## Architecture overview

At a high level, the system separates four concerns:

1. **CROCO source code** (unchanged, versioned upstream)
2. **Experiment definitions** (your science)
3. **Execution environment** (Docker / HPC abstraction)
4. **Human reasoning** (you — optionally assisted by a GPT copiloto)

Only (2) lives in this repository.

---

## Typical workflow (happy path)

This is the *minimal* path from zero to a running experiment:

1. **One-time setup**
   
   ```bash
   source setup.sh
   ```
   
   Prepares the local environment and verifies basic dependencies.

2. **Create a new experiment**
   
   ```bash
   ./create_experiment.sh EXP_MY_FIRST_CASE
   ```
   
   This copies a canonical template experiment and gives you a clean, isolated workspace.

3. **Adjust the experiment configuration**
   
   - compilation directives
   - parameter files
   - forcing / grid paths
   
   (You may do this manually, or with the help of the GPT copiloto.)

4. **Compile the experiment**
   
   ```bash
   ./compile_experiment.sh EXP_MY_FIRST_CASE
   ```

5. **Run the experiment**
   
   ```bash
   ./run_experiment.sh EXP_MY_FIRST_CASE
   ```

6. **Analyze results**
   Outputs, logs, and diagnostics live *inside the experiment folder*.

---

## Why experiments are compiled separately

In CROCO, **compile-time directives define the effective model equations**.

Changing a CPP flag is not a minor tweak: it can change

- which physical processes exist
- which state variables are evolved
- which numerical operators are compiled

Therefore:

> Two experiments with different compilation flags are *not* the same model.

For scientific traceability, each experiment is compiled in isolation, with its own binary.

---

## Repository structure

```text
CROCOEXP_BUILDER/
├── CROCO/                  # CROCO source tree (read-only)
├── CROCO_EXPERIMENTS/       # All experiments live here
│   ├── 001_TEMPLATE_EXPERIMENT/
│   ├── EXP_MY_FIRST_CASE/
│   └── ...
├── setup.sh
├── create_experiment.sh
├── compile_experiment.sh
├── run_experiment.sh
└── README.md
```

Only `CROCO_EXPERIMENTS/` is meant to be modified during research.

---

## The GPT copiloto (strongly recommended)

CROCO has a steep learning curve, largely because:

- key decisions are made at compile time
- documentation is fragmented
- many errors only appear after long runs

For this reason, we recommend using an **external GPT copiloto** that:

- proposes reasonable presets
- explains trade-offs
- anticipates common configuration errors
- helps interpret compilation and runtime logs

Important clarifications:

- The GPT **does not execute code**.
- The GPT **does not modify your system**.
- The GPT **proposes**; the researcher decides.

You are the one who signs the paper 🙂

---

## Design philosophy

- **Maximum user freedom**
- **No hidden magic**
- **Explicit over implicit**
- **Experiments are first-class objects**

This framework assumes the user is a scientist, not a button-clicker.

---

## Who should use this

- Research teams working with CROCO
- Users running multiple configurations
- Anyone who values reproducibility and clarity over convenience wrappers

If you are looking for a “one-click ocean simulator”, this is not it.

---

## Status

This project is under active development and intended for **community use within research teams**.

Contributions, discussion, and careful skepticism are welcome.
