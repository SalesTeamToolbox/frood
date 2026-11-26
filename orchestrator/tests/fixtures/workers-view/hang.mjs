// Fixture child that outlives any timeout (the test injects a short one); the view must kill it.
setTimeout(() => {}, 60_000);
