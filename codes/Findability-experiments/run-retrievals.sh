#!/bin/bash

printf "WT10g - LM-Dir\n"

cd ParallelRetrievals-JavaLucene/src
javac -cp ".:../lib/*" FindabilityExperiment.java
java -Xmx8g -cp ".:../lib/*" FindabilityExperiment

printf "\n"
printf "WT10g - DFR PL2\n"

cd ../src2
javac -cp ".:../lib/*" FindabilityExperiment.java
java -Xmx8g -cp ".:../lib/*" FindabilityExperiment
