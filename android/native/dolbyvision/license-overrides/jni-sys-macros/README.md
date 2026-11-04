# Missing crate-archive license texts

`jni-sys-macros` 0.4.1 is a build-time proc macro. Its published crate declares
MIT OR Apache-2.0 but omits the repository-root license texts. These copies are
from its `.cargo_vcs_info.json` source commit, not from a moving branch:

- https://github.com/jni-rs/jni-sys/blob/64d77b7a5f119d7b55b4e2c169a4668067ff59e6/LICENSE-MIT
- https://github.com/jni-rs/jni-sys/blob/64d77b7a5f119d7b55b4e2c169a4668067ff59e6/LICENSE-APACHE
