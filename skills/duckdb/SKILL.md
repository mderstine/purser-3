# DuckDB Skill

Use this skill when work in the current repository depends on local analytics,
inspection, or SQL execution through DuckDB.

## When To Use

- opening or creating DuckDB database files
- running ad hoc SQL from the CLI
- inspecting local data files with SQL
- deciding whether CLI usage is enough or a client library is more appropriate
- installing or loading DuckDB extensions

## Core Workflow

1. Decide whether the task is a one-off CLI query or part of a larger program.
2. Use the CLI for direct inspection, ad hoc SQL, and local data workflows.
3. Use a client library only when the task needs application integration rather
   than a direct command-line query.
4. Be explicit about extension loading when a feature is not built in.

## CLI Basics

- `duckdb` starts an in-memory database when no file is provided.
- `duckdb path/to/file.duckdb` opens or creates a persistent database file.
- `.open path/to/file.duckdb` switches the current CLI session to another
  database.
- `.open --readonly existing.duckdb` opens an existing database without writes.
- End SQL statements with `;`. Without it, the CLI keeps accepting multi-line
  input.

## Common Usage Patterns

- One-shot query against memory:
  `duckdb :memory: "SELECT 42 AS answer;"`
- Run SQL from a file:
  `.read queries.sql`
- Switch output shape for downstream tooling:
  `.mode csv`
  `.mode json`
- Read from stdin or write to stdout when composing with shell pipelines.

## CLI Versus Client Libraries

- Prefer the CLI for exploration, local validation, and repeatable shell-based
  data inspection.
- Prefer a client library when the query must be embedded in Python or another
  application runtime, or when the result needs to flow directly into program
  logic.
- DuckDB's client overview documents that clients share the same SQL syntax and
  on-disk database format, so moving between CLI and client code is usually a
  packaging decision rather than a SQL dialect decision.

## Extensions

- Explicit extension management uses SQL:
  `INSTALL extension_name;`
  `LOAD extension_name;`
- `INSTALL` fetches the extension if needed. `LOAD` activates it for the
  current connection.
- Many core extensions autoload when first used, but not all extensions do.
- If an extension changes behavior significantly or is not autoloadable, load it
  explicitly instead of assuming DuckDB will do it for you.
- Repository-qualified installs exist, so be deliberate about where an
  extension comes from.

## Operational Notes

- `-readonly` is the safer default when inspection does not require writes.
- `-csv` and `-json` are useful for scripting output.
- `.help` shows available dot commands.
- `.open` replaces the current connection. Use `ATTACH` if the task needs both
  the current database and another one at the same time.
- `~/.duckdbrc` can affect CLI behavior. Use `duckdb -init /dev/null` when a
  neutral session matters.

## Sources

- Official DuckDB CLI docs: https://duckdb.org/docs/stable/clients/cli/overview
- Official DuckDB client overview: https://duckdb.org/docs/stable/clients/overview
- Official DuckDB extension docs: https://duckdb.org/docs/current/extensions/overview
- Design reference: https://github.com/duckdb/duckdb-skills
