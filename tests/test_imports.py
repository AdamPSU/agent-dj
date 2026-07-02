"""Import checks for the initial package skeleton."""


def test_package_modules_import() -> None:
    import claude_dj
    import claude_dj.adapters.deezer
    import claude_dj.adapters.spotify
    import claude_dj.audio.embeddings
    import claude_dj.audio.previews
    import claude_dj.cli
    import claude_dj.config
    import claude_dj.daemon
    import claude_dj.errors
    import claude_dj.models
    import claude_dj.recommendation.similarity
    import claude_dj.storage.db

    assert claude_dj.__version__ == "0.1.0"
