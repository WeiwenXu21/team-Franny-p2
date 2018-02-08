import argparse
import re
import json
import os.path
import numpy as np
import string
from operator import add

from pyspark import SparkContext
from pyspark.ml.feature import NGram
from pyspark.sql import SparkSession

def Ngram_opcode(N, opcodes_rdd):
    opcodes_rdd = opcodes_rdd.groupByKey().map(lambda x: (x[0],list(x[1])))
    df = spark.createDataFrame(opcodes_rdd).toDF("file_names", "opcodes")
    ngram = NGram(n=N, inputCol="opcodes", outputCol="ngrams")
    ngramDataFrame = ngram.transform(df)
    nopcode_rdd = ngramDataFrame.rdd.map(tuple).map(lambda x: (x[0],x[2])).flatMapValues(lambda x: x)
    nocode_rdd_count = nopcode_rdd.map(lambda x: ((x),1)).reduceByKey(add)
    return nocode_rdd_count

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description = "CSCI 8360 Project 2",
                                     epilog = "answer key", add_help = "How to use",
                                     prog = "python p1.py [training-data-folder] [training-label-folder] [testing-data-folder] [optional args]")
        
    # Required args
    parser.add_argument("paths", nargs=3, #required = True
                        help = "Paths of training-data, training-labels, and testing-data.")
#    parser.add_argument("ptrain", help = "Directory of training data and labels")
#    parser.add_argument("ptest", help = "Directory of testing data and labels")

    # Optional args
#    parser.add_argument("-s", "--size", choices = ["vsmall", "small", "large"], default = "vsmall",
#                        help = "Sizes to the selected file: \"vsmall\": very small, \"small\": small, \"large\": large [Default: \"vsmall\"]")
    parser.add_argument("-o", "--output", default = ".",
                        help = "Path to the output directory where outputs will be written. [Default: \".\"]")
#    parser.add_argument("-a", "--accuracy", default = True,
#                        help = "Accuracy of the testing prediction [Default: True]")



    args = vars(parser.parse_args())
    sc = SparkContext()
    
    training_data = args['paths'][0]
    training_label = args['paths'][1]
    testing_data = args['paths'][2]

    # Read in the data
    raw_rdd_train_file_data = sc.wholeTextFiles(training_data)
    
    # ----Ngram opcode extraction---------------------
    file_name_pattern = re.compile(r'([a-zA-Z0-9]+)\.asm')
    opcode_pattern = re.compile(r'([\s])([A-F0-9]{2})([\s]+)([a-z]+)([\s+])')
    opcodes_rdd = raw_rdd_train_file_data.map(lambda x: (file_name_pattern.findall(x[0]),opcode_pattern.findall(x[1]))).flatMapValues(lambda x:x).map(lambda x: (x[0][0],x[1][3]))
    
    one_gram_opcode = Ngram_opcode(1, opcodes_rdd)
    two_gram_opcode = Ngram_opcode(2, opcodes_rdd)
    three_gram_opcode = Ngram_opcode(3, opcodes_rdd)
    four_gram_opcode = Ngram_opcode(4, opcodes_rdd)
#    print(four_gram_opcode.take(100))



