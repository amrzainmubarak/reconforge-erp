# Grouped matching replay synthetic profile

This profile evaluates four bounded partitions covering one-to-many,
many-to-one, true many-to-many, and portfolio partial settlement. The public
strategy adapter and application boundary must produce the same decision
digests. Partition effects are persisted through the durable-job service.

The first run injects a fault after one committed partition. The retry owner
must skip that effect and produce the same effect-set digest as an
uninterrupted baseline. The profile also mutates one amount by one cent and
requires the output digest to change. This is an adversarial regression
sentinel, not a mutation-testing tool score.
