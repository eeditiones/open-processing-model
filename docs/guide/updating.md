# Keeping a project up to date

`opm init` copies templates, stylesheets, an ODD and other files into your
project. Once they are there, they are yours: you can change them as you like.
But new versions of opm sometimes improve these files too, for example by
fixing a template or a stylesheet. `opm update` brings those improvements into
your project without losing your own changes.

## How it works

When `opm init` creates a project, it also writes a small file,
`.opm/init.json`. It notes which files opm wrote and what each of them looked
like at the time. Keep this file, and commit it to version control along with
the rest of your project.

When you run `opm update`, opm looks at every file it once wrote and compares
three versions: the one it wrote back then, the one in your project now, and
the one the installed opm would write today.

- If opm's version has not changed, nothing happens, even if you edited the file.
- If opm's version changed and you never touched the file, it is replaced
  with the new one.
- If both you and opm changed the file, your copy stays exactly as it is. The
  new version is saved next to it, with `.opm-new` added to its name, so you can
  compare the two and copy over what you need.

Your `opm.toml` is never replaced, because it holds your project's settings. If
opm would now write it differently, you get an `opm.toml.opm-new` to look at.

Files that you deleted are not brought back, and files that opm no longer
ships are not deleted.

## Updating step by step

1. Upgrade opm itself (see [Installation](../getting-started/installation.md)).

2. In your project directory, see what would change:

    ```bash
    opm update
    ```

    This only prints a list and writes nothing.

3. If the list looks right, make the changes:

    ```bash
    opm update --apply
    ```

4. For each `.opm-new` file, compare it with your own copy and merge what you
   want to keep. A version-control tool or any editor that compares two files
   helps here. When you are done, tell opm, which also removes the `.opm-new`
   file:

    ```bash
    opm update --resolve templates/chapbook.html.tpl --apply
    ```

If you would rather take opm's new version of every changed file and drop your
own edits, use `opm update --apply --theirs`. This never applies to `opm.toml`.

## Profiles

[Profiles](profiles.md) are not copied into your project, so they need no
updating: a new version of opm brings new versions of its profiles with it.
A new version of a profile may expect something different from your project,
though, such as a new setting. `opm update` therefore lists every profile
whose version changed since you last updated, and warns you when the first
number of the version went up, which marks a bigger change. Read what changed
with `opm profile show <name>`.

If you keep your own copy of a profile in the project's `profiles/` folder, opm
leaves it alone, but tells you when the profile that comes with opm has a
different version.
