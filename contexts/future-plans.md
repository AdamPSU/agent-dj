# Claude DJ future plans

## Optional mood detection

Mood detection should remain opt-in and should not be required for the baseline local DJ mode. A future version can add local camera or microphone analysis to infer mood, energy, or engagement, but raw camera/audio data should stay local unless a separate design review and explicit user consent approve otherwise.

Potential future mood signals:

- Facial expression or posture from a local camera model.
- Voice, humming, singing, or ambient energy from local audio analysis.
- Coding-session signals such as long pauses, repeated failures, or explicit user commands.
- Positive engagement signals such as smiling, dancing, or bopping along.

Open questions:

- Which local model should analyze mood?
- Should mood mode use camera only, microphone only, both, or neither by default?
- How often should the daemon sample signals?
- How should Claude DJ decide that a mood signal is confident enough to act on?
- How should users inspect, disable, or delete mood-derived history?

## Audio embeddings and vector search

Do not make audio embeddings mandatory for MVP. The current v1 direction is to sync a user's Spotify playlists, resolve tracks by ISRC, and keep local embeddings behind a provider gate. A provider must support ISRC resolution, expose preview or audio that can be analyzed locally, avoid paid developer-program enrollment for normal users, and allow the intended download/cache/embedding workflow. The current provider sweep found no clean default.

Current prototype exception: the local app is using Deezer previews to prove the end-to-end catalog and recommendation loop. This is a technical prototype choice, not a product-default licensing decision. The current implementation uses local MuQ only, with `OpenMuQ/MuQ-large-msd-iter`, 1024-dimensional embeddings, and 24 kHz preview decoding.

The immediate future work after first playback orchestration is richer Spotify control, not more model/provider research. Useful next steps include skip/stop commands, transfer playback, user feedback, and monitoring/repairing cases where user queue edits, skips, or Spotify queue behavior interrupt a DJ block after the first track.

Safer future architecture:

```text
Spotify or Apple Music = playlist sync, metadata, playback
Licensed audio source = only source used for audio embeddings
Local DB = metadata + permitted audio embeddings + user feedback
DJ controller = uses provider APIs, feedback, optional mood, and embeddings when available
```

The recommendation engine should not depend on embedding the user's full Spotify library. A local vector DB can be used when a permitted preview or audio source is configured, but any broader product path should only populate embeddings from audio sources with explicit rights.

Current provider decision:

- Spotify remains usable for playlist sync, metadata, and playback, but not audio or ML ingestion.
- Apple/iTunes should not be the default preview resolver: iTunes Search lacks documented ISRC lookup, and Apple Music's ISRC path requires developer tokens.
- Deezer is technically low-friction and strong for ISRC-to-preview matching, but terms make it a risky local prototype path and not a product default.
- Apify's Apple Music actor is not a clean workaround because it documents search terms, start URLs, and Apple IDs, not direct ISRC lookup or preview/audio output, and requires an Apify token plus usage-based billing.
- Production mainstream-catalog embeddings require explicit licensing terms from a commercial provider.

## Licensing research summary

### Spotify Developer Policy

URL: https://developer.spotify.com/policy

Spotify explicitly blocks the embedding workflow. Policy says not to use Spotify Platform or Spotify Content to train a machine learning or AI model or otherwise ingest Spotify Content into a machine learning or AI model. Spotify previews are also restricted to promoting the underlying content, not personalization. Not usable for MuQ embeddings.

### Spotify Developer Terms

URL: https://developer.spotify.com/terms

Spotify defines Spotify Content broadly: sound recordings, metadata, playlists, user data, lyrics, cover art, and related content. This means even playlist metadata or preview clips are risky as ML input. Spotify can still be used for playlist sync and playback, but not as an embedding source.

### Apple Music API

URL: https://developer.apple.com/documentation/applemusicapi/

Apple Music API supports catalog data, library data, recommendations, playback history, ISRC filtering, and previews. It exposes preview objects, but does not grant clear rights for ML analysis or embedding storage. It also requires Apple developer tokens, which makes it a poor default for a local-first app aimed at normal end users.

### Apple Music API Preview object

URL: https://developer.apple.com/documentation/applemusicapi/preview

Apple exposes preview `url` and `hlsUrl`. These previews are technically useful, but they are not an approved default embedding source because MusicKit/Apple Music access is token-gated and does not clearly permit local audio analysis or derived embedding storage.

### MusicKit

URL: https://developer.apple.com/musickit/

MusicKit lets apps play Apple Music and access the user's local music library with permission. It does not expose raw audio files for analysis. Useful for playback and library UX, not enough for embeddings.

### Apple Developer Program License Agreement

URL: https://developer.apple.com/support/terms/apple-developer-program-license-agreement/

MusicKit Content cannot be downloaded, uploaded, or modified unless Apple permits it. This makes Apple Music streams and previews unsafe for embedding without explicit permission.

### iTunes Search API

URL: https://performance-partners.apple.com/search-api

The iTunes Search API exposes `previewUrl`, a 30-second preview file, but it does not document ISRC lookup support. Live `lookup?isrc=...` checks returned zero results, so it is not viable as the ISRC-based preview resolver.

### Apify Apple Music actor

URL: https://apify.com/jupri/apple-music

The `jupri/apple-music` actor accepts search queries, start URLs, Apple Music IDs, and AQL-style commands such as `song:<id>`. Its input schema does not document an ISRC field, and the README's output sample is a placeholder rather than evidence of preview/audio URLs. It is community maintained, requires an Apify account token for API use, and costs $5 per 1,000 results. Not a default preview provider.

### Deezer API Terms

URL: https://developers.deezer.com/termsofuse

Deezer exposes 30-second previews and has a working unauthenticated `track/isrc:<ISRC>` path in practice. This is low-friction technically. Use the community-observed `50 requests / 5 seconds / IP` threshold as the practical rate limit unless better evidence appears. The concern is policy, not mechanics: terms are non-commercial and prohibit bypassing protections to download content. It is technically promising for a local prototype, but not viable for product use without explicit permission.

### Deezer Developer FAQ

URL: https://support.deezer.com/hc/en-gb/articles/360011538897-Deezer-FAQs-For-Developers

FAQ says only 30-second previews are available for legal reasons and full audio is not available through the API. Reinforces that Deezer is not a clean embedding source.

### Deezer Track API

URL: https://developers.deezer.com/api/track

Track objects include preview, ISRC, BPM, gain, and readable fields. Technically useful for matching, but terms block or undermine commercial embedding use.

### Feed.fm Pricing

URL: https://www.feed.fm/pricing-page

Feed.fm has custom pricing based on business needs, song plays, and soundtrack package. No public low-cost API tier for the main music API.

### Feed.fm Music API

URL: https://www.feed.fm/music-api

Feed.fm provides licensed music APIs and SDKs for apps. Good licensed playback and integration provider, but not automatically an embedding source.

### Feed Clips API

URL: https://www.feed.fm/clips/music-api

Feed Clips provides licensed major-label clips, including a Warner Music Group partnership. Technically promising because it exposes secure audio files or clips, but the terms explicitly block AI use.

### Feed Clips Terms

URL: https://www.feed.fm/clips-terms-conditions

Explicitly prohibits caching or storing API Content except limited metadata caching, and prohibits using API Content with artificial intelligence. Not usable for MuQ embeddings without separate written permission.

### Feed Originals

URL: https://www.feed.fm/originals

Most promising low-cost Feed.fm option. Wholly owned functional music catalog for fitness, focus, relaxation, meditation, sleep, and wellness. Public pricing says subscription access starts at $25 per track, in-person streaming starts at $75 per location, and in-app streaming requires a quote. It is not a user Spotify playlist match, but could be a sandbox or prototype catalog.

### Feed Originals Partner Page

URL: https://www.feed.fm/originals-partner-page

Says Feed Originals is wholly owned by Feed.fm, available to stream or download, royalty-free, and globally licensed. Did not explicitly grant AI embedding rights.

### Feed Originals Terms

URL: https://www.feed.fm/originals/terms-and-conditions

Allows downloads and copies for sync uses and limited trimming or cropping, but does not explicitly allow ML analysis or embeddings. Potentially usable only if Feed.fm grants explicit permission.

### Feed Originals Athletech

URL: https://www.feed.fm/originals-athletech

Confirms annual subscription model and broad use/download rights for Feed Originals. Still does not explicitly grant embedding rights.

### Warner Music Group and Feed.fm partnership

URL: https://www.wmg.com/news/warner-music-group-and-feed-fm-partner-to-bring-premium-music-clips-to-apps

Confirms Feed Clips has major-label and Warner catalog backing. Does not help with embeddings because Feed Clips terms prohibit AI use.

### MassiveMusic Music Delivery API

URL: https://massivemusic.com/services/platform-music-delivery-services/api-music-delivery

Strong B2B candidate. Claims 150M+ tracks, licensed delivery, rights management, reporting, and content storage. No public pricing. Likely enterprise/custom quote. Could be viable only if the contract explicitly grants ML inference and derived embedding storage.

### MassiveMusic API docs

URL: https://docs.massivemusic.com/reference/introduction

Public REST API docs. Good API maturity signal. Pricing not listed. Does not directly grant embedding rights.

### MassiveMusic FAQ

URL: https://massivemusic.com/faq

Pricing depends on project scope, technical requirements, and rights involved. Confirms custom pricing. Not intern-budget.

### MassiveMusic home

URL: https://www.massivemusic.com/

Good reputation signals: platform and music delivery services, APIs for metadata, delivery, rights, and reporting, and major brand examples. Does not solve cost or embedding-rights question.

### Music Business Worldwide on MassiveMusic consolidation

URL: https://www.musicbusinessworldwide.com/songtradr-brings-together-key-b2b-businesses-under-massivemusic-brand/

Confirms Songtradr consolidated 7digital, Big Sync Music, Musicube, and Resonance under MassiveMusic. Good reputation signal, especially 7digital and Musicube. Still enterprise.

### 7digital and Triller coverage

URLs surfaced via Music Business Worldwide, Music Week, PR Newswire, and CelebrityAccess.

Used as reputation evidence for MassiveMusic and 7digital lineage. 7digital historically powered large catalog access for Triller. Not a direct low-cost embedding source.

### Tuned Global Streaming/Music APIs

URL: https://www.tunedglobal.com/streaming-services/streaming-music-api-for-apps

B2B streaming infrastructure with 500+ APIs, 100M+ tracks upon licensing, content delivery, analytics, and rights management. No public pricing. More suited to launching a full streaming service than a tiny plugin MVP.

### Tuned Global Case Studies

URL: https://www.tunedglobal.com/tuned-global-white-label-music-solutions-case-studies

Strong reputation signals: Lululemon, Delta, Sony Music, LINE Music, Samsung, Gabb, Reactional Music, and others. Still enterprise/custom and not explicitly an embedding source.

### Tuned Global Contact

URL: https://www.tunedglobal.com/contact

Confirms sales/contact route, no public pricing. Not intern-budget.

### SourceAudio official API

URLs:

- https://www.sourceaudio.com/api/
- https://docs.sourceaudio.com/api/index.html

SourceAudio API supports metadata, ISRC, search, upload/download of audio files, and catalog tooling. Requires being a SourceAudio customer.

### SourceAudio AI dataset licensing marketplace

URLs:

- https://www.sourceaudio.com/blog/2025/06/05/a-new-chapter-in-music-licensing/
- https://www.sourceaudio.com/blog/2025/06/26/your-sourceaudio-june-recap-ethical-ai-real-revenue-whats-coming-next/
- https://www.recordoftheday.com/news-and-press/sourceaudio-establishes-the-first-scalable-fully-cleared-ai-music-dataset-licensing-marketplace

Best fit for explicitly cleared AI dataset licensing. Claims 14M songs, 3M SFX, 200 sampled instruments, opt-in rightsholder licensing, and a fully cleared AI dataset marketplace. Likely enterprise contract, not intern-budget.

### SourceAudio AI Metadata FAQ

URL: https://www.sourceaudio.com/blog/2023/10/24/ai-metadata-faqs/

Confirms SourceAudio itself does AI metadata tagging and audio analysis. Useful signal that they operate in this area. Does not give us free access or rights.

### Jamendo API

URL: https://developer.jamendo.com/v3.0/tracks

Jamendo exposes audio fields, download fields, licenses, and `audiodownload_allowed`. Potentially useful for open or independent catalog experiments. Does not match mainstream Spotify playlists and may have commercial limitations depending on license.

### MTG-Jamendo Dataset

URL: https://mtg.github.io/mtg-jamendo-dataset/

Open dataset with 56k+ full tracks from Jamendo under Creative Commons licenses, designed for music auto-tagging and audio analysis. Good research or prototype source. Mostly non-commercial/research and not mainstream playlist coverage.

### Freesound API Terms

URL: https://freesound.org/help/tos_api/

Freesound terms explicitly allow processing and analyzing content according to each sound's license. Good for sound or sample experiments, not a song catalog matching user playlists. Commercial API use requires separate negotiation.

### Epidemic Sound Terms

URL: https://www.epidemicsound.com/policy/general-terms-and-conditions/

Bad fit. Terms explicitly prohibit text/data mining and machine learning analysis except through sanctioned connector/API terms. Not a workaround.

### Epidemic Sound Developer/API pages

URLs:

- https://www.epidemicsound.com/business/developers/
- https://developers.epidemicsound.com/

Possible sanctioned API route, but public terms still require explicit permission and do not create a low-cost automatic embedding source.

### Cyanite

URL: https://cyanite.ai/blog/music-analysis-api/

Cyanite is an AI music tagging and search provider. Useful for understanding the market. It analyzes catalogs customers have rights to. It does not provide mainstream audio to embed.

### Musiio

URL: https://docs.musiio.com/tag/

Musiio provides AI tagging and search for audio files. Like Cyanite, it expects the customer to have audio rights. Not a source of licensed mainstream audio.

### AIMS API

URL: https://www.aimsapi.com/

AI music similarity and search provider for catalogs. Useful for catalog owners, not a source of licensed user playlist audio.

### MusicAtlas

URL: https://musicatlas.ai/intelligence/music-search-api-what-you-can-build

Provides embeddings, search, and recommendation infrastructure, but requires users to supply their own catalog. Not an audio licensing source.

### Soundcharts music API guide

URL: https://soundcharts.com/en/blog/music-data-api

General comparison and research source. Helped identify providers. Not an audio source.

### Bridge.audio API guide

URL: https://www.bridge.audio/blog/the-best-apis-for-music-industry-professionals/

General industry API overview. Not an audio source.

## Model research

### MuQ paper

URL: https://arxiv.org/abs/2501.01108

MuQ is a newer music-specific representation model. Strong candidate for audio embeddings. Code and checkpoints are open, but model weights are CC-BY-NC 4.0, which blocks straightforward commercial use.

### MuQ GitHub

URL: https://github.com/tencent-ailab/MuQ

Official implementation. Code MIT, weights CC-BY-NC 4.0. Good for experiments, not clean commercial default.

### CLAP paper

URL: https://arxiv.org/abs/2206.04769

Baseline audio-text embedding approach. Useful background, but the implementation is MuQ-only for audio-to-audio similarity.

### 2026 pretrained audio representations for music recommender systems

URL: https://arxiv.org/abs/2604.23077

Compared MusicFM, Music2Vec, MERT, EncodecMAE, Jukebox, MusiCNN, MULE, MuQ, and joint audio-text baselines for recommender systems. Found MuQ consistently promising, but no single model wins everywhere.

### 2026 perceptual music similarity with pretrained embeddings

URL: https://arxiv.org/abs/2601.19109

Found audio-text and audio-only pretrained embeddings are strong baselines for perceptual music similarity. Also suggested source-separated, instrument-weighted similarity can improve alignment with human judgment. Good future research, not MVP.

### 2024 CLAP embeddings for recommender tasks

URL: https://arxiv.org/abs/2409.09026

Found CLAP embeddings can help recommender tasks. Supports the general audio-embedding direction, but does not solve licensing.

### Other CLAP improvement papers surfaced

T-CLAP, M2D-CLAP, GLAP, RobustCLAP, CoLLAP, SLAP, AuroLA, Omni-Embed-Audio, Spatial-CLAP, and FIGMA were surfaced as related research. They may improve audio-text embeddings, temporal modeling, multilingual support, or fine-grained retrieval. None solve the licensing/audio-source problem.

## Future recommendation path

1. Keep the baseline DJ useful with Spotify metadata, playback state, feedback, skips, and commands.
2. Add mood mode only as an explicit opt-in feature.
3. Keep the local vector DB design optional.
4. Populate embeddings only from audio sources with explicit rights.
5. Use Feed Originals with permission, MTG-Jamendo, or Freesound as cheap prototype embedding sources.
6. Revisit SourceAudio, MassiveMusic, Tuned Global, or Feed.fm custom terms only if the project becomes funded or needs mainstream catalog embeddings.
