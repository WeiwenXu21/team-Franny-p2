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

def RF(features_count_rdd):
    distinct_feature = features_count_rdd.map(lambda x: x[0][1]).distinct().sortBy(lambda x: x)
    distinct_feature_index = distinct_feature.zipWithIndex()
    #    print(distinct_feature.collect())
    train_name = rdd_train_name.collect()
    feature_filename = distinct_feature.map(lambda x: (x,train_name)).flatMapValues(lambda x:x)
    feature_filename_zero = feature_filename.map(lambda x: ((x[1],x[0]),0))
    
    full_feature_no_label = features_count_rdd.union(feature_filename_zero).reduceByKey(add)
    full_feature_no_label = full_feature_no_label.map(lambda x: (x[0][0],(x[0][1],x[1])))
    full_feature = label_filename_pair.join(full_feature_no_label)
    full_feature_nofilename = full_feature.map(lambda x: (x[1][0],x[1][1])).sortBy(lambda x:x[1][0])
    full_feature_wl = full_feature_nofilename.map(lambda x: (x[0],x[1][1])).groupByKey().map(lambda x:(x[0],Vectors.dense(list(x[1]))))
    #    print(full_feature_nofilename.collect())
    #    full_feature_wl = full_feature_wl.map(lambda x: (x[0],Vectors.sparse(x[1])))
    
    #<-----Probaby have bug here-------------------
    df = spark.createDataFrame(full_feature_wl).toDF("label", "features")
    #    df.show()
    stringIndexer = StringIndexer(inputCol="label", outputCol="indexed")
    si_model = stringIndexer.fit(df)
    td = si_model.transform(df)
    ##    td.show()
    rf = RandomForestClassifier(numTrees=3, maxDepth=2, labelCol="indexed", seed=42)
    model = rf.fit(td)
    return model.featureImportances

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
    
    file_name_pattern = re.compile(r'([a-zA-Z0-9]+)\.asm')
    file_data_rdd = raw_rdd_train_file_data.map(lambda x: (file_name_pattern.findall(x[0]),x[1])).map(lambda x: (x[0][0],x[1]))
    
    # ----Ngram opcode extraction---------------------
    opcode_pattern = re.compile(r'([\s])([A-F0-9]{2})([\s]+)([a-z]+)([\s+])')
    opcodes_rdd = file_data_rdd.map(lambda x: (x[0],opcode_pattern.findall(x[1]))).flatMapValues(lambda x:x).map(lambda x: (x[0],x[1][3]))
    
    Ngram_opcode_list = []
    for i in range(4):
        Ngram_opcode_list.append(Ngram_opcode(i+1, opcodes_rdd))
    Ngram_opcode_count = sc.union(Ngram_opcode_list)
#    print(Ngram_opcode_count.collect())

    # ----Segment Count extraction--------------------
    segment_pattern = re.compile(r'([a-zA-Z]+):[a-zA-Z0-9]{8}')
    segment_rdd = file_data_rdd.map(lambda x: (x[0],segment_pattern.findall(x[1]))).flatMapValues(lambda x:x)
    segment_rdd_count = segment_rdd.map(lambda x: ((x),1)).reduceByKey(add)
#    print(segment_rdd_count.collect())

    segment_RF = RF(segment_rdd_count)
    print(segment_RF) #<- bug here








