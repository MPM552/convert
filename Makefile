create:
	singularity build --fakeroot convert.sif convert.def
run:
	./convert.sif
