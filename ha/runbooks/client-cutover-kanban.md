# PostgreSQL HA client cutover Kanban

Each application is an independent reversible wave. Research may run in parallel, but only one cutover card may be in progress at a time.

## Rules for every card

1. Identify every active instance and its owning host/Compose source.
2. Capture the current credential-free endpoint shape and rollback copy.
3. Select the nearest HAProxy listener:
   - Armadillo-hosted consumers: `100.64.0.5:6432`.
   - Rogue-hosted consumers: `100.64.0.4:6432`.
   - Fluffy-hosted consumers: `100.64.0.2:6432`.
   - Office/pi1 consumers: `100.64.0.1:6432`.
4. Patch the durable source, not only the running container.
5. Recreate only the application service with `--force-recreate --no-deps` unless its documented reload mechanism is safer.
6. Verify process/container health, application behavior, authenticated SQL, writable-primary routing, and the expected HAProxy/PgBouncer connection source.
7. Preserve a credential-free rollback record. Roll back before moving to the next card if acceptance fails.
8. Mark a card done only after the previous direct sessions have drained.

## Board

### In progress

- [ ] Inventory every direct PostgreSQL consumer, owning host/stack, configuration source, and nearest HAProxy endpoint.

### Ready

- [ ] Hermes/Pixu memory clients
- [ ] Penpot
- [ ] Astream
- [ ] Comet
- [ ] IPTV production
- [ ] Kutt
- [ ] Matrix Synapse
- [ ] Stalwart
- [ ] Zabbix server
- [ ] Vaultwarden
- [ ] Affine
- [ ] NocoDB
- [ ] Mattermost
- [ ] Cal.com
- [ ] PostgreSQL monitoring clients
- [ ] Final zero-direct-client and failover-readiness verification

### Done

- None yet.
