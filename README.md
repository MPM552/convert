# convert

Unit Conversion Program

'make create' will create the container using a singularity "build from def file" command

'make run' starts a python web server on the localhost at port 8000

Access the main project page at localhost:8000/cgi-bin/convert.cgi in your browser of choice

convert.cgi currently has a divide by zero error that is apparent when building the container.

However, it will run locally using the one-line python server and necessary dependencies.

For help installing Singularity:
  https://sylabs.io/guides/3.5/user-guide/quick_start.html
  
Note: This is a difficult process on non-Linux machines



