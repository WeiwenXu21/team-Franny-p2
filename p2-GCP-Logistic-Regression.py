# -*- coding: utf-8 -*-
"""
Created on Sat Feb 10 21:26:51 2018

@author: ailingwang

py2 GCP version. Most code is based on Weiwen Xu's work
"""

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
from pyspark.ml.classification import LogisticRegression

from pyspark.sql.functions import udf
from pyspark.sql.types import *


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

def create_feature_label_rdd(features_count_rdd,label_filename_pair):
    '''
        Random Forest for ranking features
        Output: Rdd with selected features. format(file_name,label,[vector of features])
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
    #ordered_features = full_feature_no_label.map(lambda x:x[1][0])

    full_feature_wl = full_feature_nofilename.map(lambda x: (x[0],x[1][1])).groupByKey()

    full_feature_wl = label_filename_pair.join(full_feature_wl).map(lambda x: (x[0],x[1][0],Vectors.dense(list(x[1][1]))))
    return full_feature_wl

def test_feature_rdd(distinct_feature, test_features_count_rdd, label_filename_pair):
    test_file_name = test_features_count_rdd.map(lambda x: x[0][0]).distinct().collect()
    feature_filename = distinct_feature.map(lambda x: (x,test_file_name)).flatMapValues(lambda x:x)
    feature_filename_zero = feature_filename.map(lambda x: ((x[1],x[0]),0))
    l = sc.broadcast(distinct_feature.collect())
    
    test_features_count_rdd = test_all_features_count.filter(lambda x: x[0][1] in l.value)
    
    full_feature_no_label = test_features_count_rdd.union(feature_filename_zero).reduceByKey(add)
    full_feature_no_label = full_feature_no_label.map(lambda x: (x[0][0],(x[0][1],x[1])))
    
    full_feature_nofilename = full_feature_no_label.sortBy(lambda x:x[1][0])
    full_feature_wl = full_feature_nofilename.map(lambda x: (x[0],x[1][1])).groupByKey()
    full_feature_wl = label_filename_pair.join(full_feature_wl).map(lambda x: (x[0],x[1][0],Vectors.dense(list(x[1][1]))))
    return full_feature_wl

def create_td(full_feature_wl):    
    #---Random Forest-------------------------------------
    df = spark.createDataFrame(full_feature_wl).toDF("name","label", "features")

    stringIndexer = StringIndexer(inputCol="name", outputCol="indexed")
    si_model = stringIndexer.fit(df)
    td = si_model.transform(df)
    return td

def RF_feature_selection(td):    
    rf = RandomForestClassifier(numTrees=6, maxDepth=5, labelCol="indexed")
    model = rf.fit(td)  
    feature_importance = model.featureImportances
    return feature_importance

def RF_feature_filter(feature_importance,full_feature_wl):
    full_feature_rf = full_feature_wl.map(lambda x: (x[0],x[1],Vectors.dense([x[2][i] for i in feature_importance.indices])))
    print(full_feature_rf.take(10))
    td_new = create_td(full_feature_rf)
    return td_new

def change_column_datatype(td,col_name,datatype):
    
    td_new = td.withColumn(col_name, td[col_name].cast(datatype()))
    return td_new

def logistic_regression(td):
    lr = LogisticRegression(labelCol="label", featuresCol="features",maxIter=10, regParam=0.3, elasticNetParam=0.8)
    
    td_new = change_column_datatype(td,"label",DoubleType)
    # Fit the model
    lrModel = lr.fit(td_new)
    return  lrModel

def get_label_filename_pair(file_data_rdd,rdd_label):
    """This function match the filename with label"""
    #rdd_train_name = file_data_rdd.map(lambda x: x[0])
    #label_filename_pair = (rdd_train_name.repartition(P)).zip(rdd_label.repartition(P))

    rdd_train_name_id = file_data_rdd.zipWithIndex().map(lambda x: (x[1],x[0]))
    rdd_label_id = rdd_label.zipWithIndex().map(lambda x: (x[1],x[0]))
    label_filename_pair = rdd_train_name_id.join(rdd_label_id).map(lambda x: x[1])
    return label_filename_pair

def extract_ngram_opcode_counts(file_data_rdd,n,train_or_test):
    """This function extract the ngram opcode counts
    It takes in file rdd, and number of grams to be calculated"""
    
     #---Extract opcodes--------------------------
    opcode_pattern = re.compile(r'([\s])([A-F0-9]{2})([\s]+)([a-z]+)([\s+])')
    opcodes_rdd = file_data_rdd.map(lambda x: (x[0],opcode_pattern.findall(x[1]))).flatMapValues(lambda x:x).map(lambda x: (x[0],x[1][3]))
    print("finished working on extracting opcode")
    #---New--------------------------------------------
    #---IDF for each opcode and filter ones with 0.0---
    if train_or_test == 'train':    
        N = train_files_rdd.count()
    elif train_or_test == 'test':
        N = test_files_rdd.count()
    else:
        N = 0
        print("3rd input is invalid")
    
    opcode_n_t = opcodes_rdd.distinct().map(lambda x: (x[1],1)).reduceByKey(add)
    opcode_idf = opcode_n_t.map(lambda x: (x[0], np.log(N/x[1]))).filter(lambda x: x[1] > 3)
    print(opcode_idf.take(30))
    useful_opcode = opcode_idf.map(lambda x: x[0]).collect()
    opcodes_rdd = opcodes_rdd.filter(lambda x: x[1] in useful_opcode)
    print("finished working on idf")
    #---Ngram opcode counts----------------------
    Ngram_opcode_list = []
    for i in range(4):
        Ngram_opcode_list.append(Ngram_opcode(i+1, opcodes_rdd))
    Ngram_opcode_count = sc.union(Ngram_opcode_list)
    print("finished working on ngram")
    
    return Ngram_opcode_count

def extract_segment_counts(file_data_rdd):
    """     This function extract the ngram opcode counts"""    
    # ----Segment Count extraction--------------------
    
    segment_pattern = re.compile(r'([a-zA-Z]+):[a-zA-Z0-9]{8}[\t\s]')
    segment_rdd = file_data_rdd.map(lambda x: (x[0],segment_pattern.findall(x[1]))).flatMapValues(lambda x:x)
    segment_rdd_count = segment_rdd.map(lambda x: ((x),1)).reduceByKey(add)
    return segment_rdd_count


def preprocess(data_msd_folder, files):
    Spark_Full = sc.emptyRDD()
    myRDDlist = []
    for filename in files.value:
        new_rdd = sc.textFile(data_msd_folder +"/"+ filename + ".asm").map(lambda x: (filename,x)).groupByKey().map(lambda x: (x[0],' '.join(x[1])))
        myRDDlist.append(new_rdd)
        
    Spark_Full = sc.union(myRDDlist)
    return Spark_Full   
    
if __name__ == "__main__":
    
    P=2
    
    sc = SparkContext()
    spark = SparkSession.builder.master("yarn").appName("Word Count").config("spark.some.config.option", "some-value").getOrCreate()
    data_msd_folder = "gs://uga-dsp/project2/data/asm/"
    training_file_names = "gs://uga-dsp/project2/files/X_small_train.txt"
    training_label = "gs://uga-dsp/project2/files/y_small_train.txt"
    test_file_names = "gs://uga-dsp/project2/files/X_small_test.txt"
    test_label = "gs://uga-dsp/project2/files/y_small_test.txt"
        
    # Read in the data
    #raw_rdd_train_name_asm_data = sc.wholeTextFile(data_msd_folder)
    rdd_label = sc.textFile(training_label)
    test_rdd_label = sc.textFile(test_label)
    
    
    train_files_rdd =sc.textFile(training_file_names)
    test_files_rdd =sc.textFile(test_file_names)
    train_files = sc.broadcast(train_files_rdd.collect())
    test_files = sc.broadcast(test_files_rdd.collect())
    
    #print(raw_rdd_train_file_data.first())
    #print(train_files.value[:10],len(train_files.value))
    sc.setCheckpointDir('checkpoint/')
    
    
    file_name_pattern = re.compile(r'([a-zA-Z0-9]+)\.asm')

    #file_data_rdd = raw_rdd_train_name_asm_data.map(lambda x:(file_name_pattern.findall(x[0]),x[1])).filter(lambda x: x[0][0] in train_files.value).map(lambda x: (x[0][0],x[1]))
    #test_file_data_rdd = raw_rdd_train_name_asm_data.map(lambda x:(file_name_pattern.findall(x[0]),x[1])).filter(lambda x: x[0][0] in test_files.value).map(lambda x: (x[0][0],x[1]))
    
    file_data_rdd = preprocess(data_msd_folder, train_files)
    file_data_rdd.persist()
    test_file_data_rdd = preprocess(data_msd_folder, test_files)
    
    
    label_filename_pair = get_label_filename_pair(train_files_rdd ,rdd_label)
    test_label_filename_pair = get_label_filename_pair(test_files_rdd,test_rdd_label)
    
    print(label_filename_pair.take(10))
    
    
    
    Ngram_opcode_count = extract_ngram_opcode_counts(file_data_rdd,3,'train')
    segment_rdd_count = extract_segment_counts(file_data_rdd)
    
    print(segment_rdd_count.take(10), Ngram_opcode_count.take(10))
    all_features_count = segment_rdd_count.union(Ngram_opcode_count).cache()
    print(all_features_count.count())
    
    
    #print(all_features_count.take(10))
    
    test_Ngram_opcode_count = extract_ngram_opcode_counts(test_file_data_rdd,3,"test")
    test_segment_rdd_count = extract_segment_counts(test_file_data_rdd)
    test_all_features_count = test_segment_rdd_count.union(test_Ngram_opcode_count).cache()
    
    
    #print(test_all_features_count.take(10))
    
    feature_label_rdd = create_feature_label_rdd(all_features_count,label_filename_pair)
    feature_label_full_td = create_td(feature_label_rdd)
    feature_label_full_td.printSchema()
    feature_importance = RF_feature_selection(feature_label_full_td) 
    opcode_RF = RF_feature_filter(feature_importance,feature_label_rdd)

    
    LG_model = logistic_regression(opcode_RF)
    
   
    #print(opcode_RF)
    
    distinct_feature = all_features_count.map(lambda x: x[0][1]).distinct().sortBy(lambda x: x)
    
    print(distinct_feature.take(10))
    
    test_feature_label_rdd = test_feature_rdd(distinct_feature, test_all_features_count, test_label_filename_pair)
    test_opcode_RF = RF_feature_filter(feature_importance,test_feature_label_rdd)
        
    result = LG_model.transform(test_opcode_RF)
    result = result.withColumn("prediction", result["prediction"].cast("int"))
    result.select("prediction","name").write.csv('gs://irene024081/output/')
    