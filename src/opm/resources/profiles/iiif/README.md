### iiif: facsimile viewer

Shows the facsimile in the right column. The viewer follows the page breaks of
the transcription, so the facsimile turns with the text.

#### Before you start

1. Switch on TEI Publisher's web components in `opm.toml`:

    ```toml
    [transform.web]
    webcomponents = true
    ```

2. Give your page breaks a facsimile: `<pb facs="…"/>`. For each one,
   `teipublisher.odd` writes the `<pb-facs-link>` element the viewer follows.
3. Choose the viewer below: `pb-tify` if you have IIIF manifests,
   `pb-facsimile` with `base_uri` if you have single images on a IIIF image
   server.

#### Settings

| Setting (`[context.features.iiif]`) | Default | Meaning |
|---|---|---|
| `viewer` | `"pb-tify"` | `"pb-tify"` for IIIF manifests, `"pb-facsimile"` for single images from a IIIF image server |
| `base_uri` | `""` | For `pb-facsimile`: the image server address each image name is added to |
| `label` | `"Facsimile"` | Read out by screen readers |

The Shakespeare example uses `pb-tify` with manifests it ships itself, the
Escher example `pb-facsimile` with the edition's image server.
