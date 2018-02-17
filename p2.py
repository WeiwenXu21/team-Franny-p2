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

from numpy import allclose
from pyspark.ml.linalg import Vectors
from pyspark.ml.feature import StringIndexer
from pyspark.ml.classification import RandomForestClassifier

def Ngram_opcode(N, opcodes_rdd):
    '''
        Extract and count N gram
        '''
    opcodes_rdd = opcodes_rdd.groupByKey().map(lambda x: (x[0],list(x[1])))
    df = spark.createDataFrame(opcodes_rdd).toDF("file_names", "opcodes")
    ngram = NGram(n=N, inputCol="opcodes", outputCol="ngrams")
    ngramDataFrame = ngram.transform(df)
    nopcode_rdd = ngramDataFrame.rdd.map(tuple).map(lambda x: (x[0],x[2])).flatMapValues(lambda x: x)
    nocode_rdd_count = nopcode_rdd.map(lambda x: ((x),1)).reduceByKey(add)
    return nocode_rdd_count

def RF(features_count_rdd,label_filename_pair):
    '''
        Random Forest for ranking features
    '''
    #---Prepare for data structure: (file_name, label, [feature1_count,feature2_count, ...])------
    f_c = features_count_rdd
    distinct_feature = f_c.map(lambda x: x[0][1]).distinct().sortBy(lambda x: x)

    train_file_name = features_count_rdd.map(lambda x: x[0][0]).distinct().collect()

    feature_filename = distinct_feature.map(lambda x: (x,train_file_name)).flatMapValues(lambda x:x)
    feature_filename_zero = feature_filename.map(lambda x: ((x[1],x[0]),0))

    full_feature_no_label = features_count_rdd.union(feature_filename_zero).reduceByKey(add)
    full_feature_no_label = full_feature_no_label.map(lambda x: (x[0][0],(x[0][1],x[1])))

    full_feature_nofilename = full_feature_no_label.sortBy(lambda x:x[1][0])
    ordered_features = full_feature_no_label.map(lambda x:x[1][0])

    full_feature_wl = full_feature_nofilename.map(lambda x: (x[0],x[1][1])).groupByKey()

    full_feature_wl = label_filename_pair.join(full_feature_wl).map(lambda x: (x[0],x[1][0],Vectors.dense(list(x[1][1]))))
    
    
    #---Random Forest-------------------------------------
    df = spark.createDataFrame(full_feature_wl).toDF("name","label", "features")

    stringIndexer = StringIndexer(inputCol="name", outputCol="indexed")
    si_model = stringIndexer.fit(df)
    td = si_model.transform(df)

    rf = RandomForestClassifier(numTrees=6, maxDepth=5, labelCol="indexed")
    model = rf.fit(td)
    
    #-------Added by Ailing, get the rdd with selected feature--------
    feature_importance = model.featureImportances
    
    full_feature_rf = full_feature_wl.map(lambda x: (x[0],x[1],[x[2][i] for i in feature_importance.indices]))
    return full_feature_rf


if __name__ == "__main__":
    sc = SparkContext()
    spark = SparkSession.builder.master("local").appName("Word Count").config("spark.some.config.option", "some-value").getOrCreate()
    
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
                                     
                                     
    #---Read in Files----------------------------
    args = vars(parser.parse_args())
        
    training_data = args['paths'][0]
    training_label = args['paths'][1]
    testing_data = args['paths'][2]
                                     
    raw_rdd_train_name_asm_data = sc.wholeTextFiles(training_data)
    rdd_label = sc.textFile(training_label)
    
    #---Extract file names-----------------------
    file_name_pattern = re.compile(r'([a-zA-Z0-9]+)\.asm')
    file_data_rdd = raw_rdd_train_name_asm_data.map(lambda x:(file_name_pattern.findall(x[0]),x[1])).map(lambda x: (x[0][0],x[1]))
    
    #---Prepare for (file_name,label)------------
    rdd_train_name = file_data_rdd.map(lambda x: x[0])
    rdd_train_name_id = rdd_train_name.zipWithIndex().map(lambda x: (x[1],x[0]))
    rdd_label_id = rdd_label.zipWithIndex().map(lambda x: (x[1],x[0]))
    label_filename_pair = rdd_train_name_id.join(rdd_label_id).map(lambda x: x[1])

    #---Extract opcodes--------------------------
    opcode_pattern = re.compile(r'([\s])([A-F0-9]{2})([\s]+)([a-z]+)([\s+])')
    opcodes_rdd = file_data_rdd.map(lambda x: (x[0],opcode_pattern.findall(x[1]))).flatMapValues(lambda x:x).map(lambda x: (x[0],x[1][3]))

    #---Ngram opcode counts----------------------
    Ngram_opcode_list = []
    for i in range(4):
        Ngram_opcode_list.append(Ngram_opcode(i+1, opcodes_rdd))
    Ngram_opcode_count = sc.union(Ngram_opcode_list)

    #---Segment counts---------------------------
    segment_pattern = re.compile(r'([a-zA-Z]+):[a-zA-Z0-9]{8}[\t\s]')
    segment_rdd = file_data_rdd.map(lambda x: (x[0],segment_pattern.findall(x[1]))).flatMapValues(lambda x:x)
    segment_rdd_count = segment_rdd.map(lambda x: ((x),1)).reduceByKey(add)

    #---Random Forest for feature ranking--------
    opcode_RF = RF(segment_rdd_count,label_filename_pair)
    print(opcode_RF.collect())




















