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
from pyspark.ml.regression import RandomForestRegressor

from pyspark.ml.classification import LogisticRegression

from pyspark.sql.functions import udf
from pyspark.sql.types import *

BYTES_PATTERN = re.compile(r'\s([A-F0-9]{2})\s')
SEGMENT_PATTERN = re.compile(r'([a-zA-Z]+):[a-zA-Z0-9]{8}[\t\s]')
OPCODE_PATTERN = re.compile(r'([\s])([A-F0-9]{2})([\s]+)([a-z]+)([\s+])')


def preprocess(data_folder_path, filenames, type):
    myRDDlist = []
    for filename in filenames[:50]:
        new_rdd = sc.textFile(data_folder_path +"/"+ filename + type).map(lambda x: (filename,x)).groupByKey().map(lambda x: (x[0],' '.join(x[1])))
        myRDDlist.append(new_rdd)
    Spark_Full = sc.union(myRDDlist)
    return Spark_Full

def get_filename_label_pair(filenames_data_rdd,labels_rdd):
    """
        This function matches the filename with label
        
        --input-------------------------------------
        filenames_data_rdd : [<hash1>, <hash2>, ...]
        labels_rdd : [label1, label2, ...]
        
        --output------------------------------------
        filename_label_pair : [(<hash1>,<label1>), (<hash2>,<label2>), ...]
    """
    
    id_filenames_rdd = filenames_data_rdd.zipWithIndex().map(lambda x: (x[1],x[0]))
    id_label_rdd = labels_rdd.zipWithIndex().map(lambda x: (x[1],x[0]))
    filename_label_pair = id_filenames_rdd.join(id_label_rdd).map(lambda x: x[1])
    return filename_label_pair

def extract_features(file_rdd, feature_name):
    """
        This function extracts the required features
        
        --input-------------------------------------
        file_rdd : [(<hash1>, <content1>), ...]
        feature_name : str
        
        --output------------------------------------
        filename_label_pair : [(<hash1>,<feature1>), (<hash1>,<feature2>), ..., (<hashN>,<featureK>)]
    """
    
    if feature_name=='bytes':
        return file_rdd.map(lambda x: (x[0],BYTES_PATTERN.findall(x[1]))).flatMapValues(lambda x:x)
    elif feature_name=='segment':
        return file_rdd.map(lambda x: (x[0],SEGMENT_PATTERN.findall(x[1]))).flatMapValues(lambda x:x)
    elif feature_name=='opcode':
        return file_rdd.map(lambda x: (x[0],OPCODE_PATTERN.findall(x[1]))).flatMapValues(lambda x:x).map(lambda x: (x[0],x[1][3]))
    else:
        return "Invalid input!"

def get_frequent_features(feature_rdd):
    '''
        This function removes features appears less than 100 times
        feature_rdd : [(<hash1>,<feature1>), (<hash1>,<feature2>), ..., (<hashN>,<featureK>)]
        '''
    feature_docwise_count_rdd = feature_rdd.map(lambda x: ((x),1)).reduceByKey(add)
    frequent_features_rdd = feature_docwise_count_rdd.filter(lambda x: x[1]>200)
    frequent_features_list = frequent_features_rdd.map(lambda x: x[0][1]).distinct().collect()
    useful_features_rdd = feature_rdd.filter(lambda x: x[1] in frequent_features_list)
    return useful_features_rdd

def Ngram(feature_rdd,start,end):
    '''
        --input-------------------------------------
        feature_rdd : [(<hash1>,<feature1>), (<hash1>,<feature2>), ..., (<hashN>,<featureK>)]
        
        --output------------------------------------
        Ngram_count : [((<hash>,<ngram feature>),cnt), ...]
        '''
    Ngram_list = []
    for i in range(start,end):
        Ngram_list.append(Ngram_feature(i, feature_rdd))
    Ngram_count = sc.union(Ngram_list)
    return Ngram_count

def Ngram_feature(N, feature_rdd):
    '''
        Extract and count N-gram
        
        --input-------------------------------------
        feature_rdd : [(<hash1>,<feature1>), (<hash1>,<feature2>), ..., (<hashN>,<featureK>)]
        
        --output------------------------------------
        freq_ngram_count_rdd : [((<hash>,<ngram feature>),cnt), ...]
        '''
    feature_rdd = feature_rdd.groupByKey().map(lambda x: (x[0],list(x[1])))
    df = spark.createDataFrame(feature_rdd).toDF("file_names", "features")
    ngram = NGram(n=N, inputCol="features", outputCol="ngrams")
    ngramDataFrame = ngram.transform(df)
    ngram_rdd = ngramDataFrame.rdd.map(tuple).map(lambda x: (x[0],x[2])).flatMapValues(lambda x: x)
    ngram_count_rdd = ngram_rdd.map(lambda x: ((x),1)).reduceByKey(add)
    freq_ngram_count_rdd = ngram_count_rdd.filter(lambda x: x[1]>100)
#    freq_ngram_count_rdd = ngram_count_rdd.filter(lambda x: x[1])
    return freq_ngram_count_rdd

def build_full_feature_list(features,length):
#    print(features.shape())
#    print(length)
#    print("$$$$$$$$$$$")
    full_feature_narray = np.zeros(length,)
    full_feature_narray[features[:,0]] = features[:,1]
    return full_feature_narray
#    return [features.shape(),length]

def test_RF_structure(all_test_features_count,distinct_features_rdd):
    '''
        all_test_features_count : [(<ngram feature>,(<hash>,cnt)), ...]
        distinct_features_rdd : [(<ngram feature>,index), ...]
        
        all_test_features_count : [(<ngram feature>,((<hash>,cnt),index)), ...]
        '''
    #--[(<ngram feature>,(<hash>,cnt)), ...]-----------------------------------------
    all_test_features_count = all_test_features_count.map(lambda x: (x[0][1],(x[0][0],x[1])))

    #--[(<ngram feature>,(index,(<hash>,cnt))), ...]-----------------------------------------
    all_test_features_count = all_test_features_count.leftOuterJoin(distinct_features_rdd).filter(lambda x: not x[1][1]==None)
    print(all_test_features_count.take(5))
    print("$$$$$$$$$$$ 4.5")

    #--[(<hash>,(index,cnt)), ...]-------------------------------------------------------
    full_features_index_count_rdd = all_test_features_count.map(lambda x: (x[1][0][0],(x[1][1],x[1][0][1]))).groupByKey().map(lambda x: (x[0],np.asarray(list(x[1]),dtype=int)))
    print(full_features_index_count_rdd.take(1))
    print("$$$$$$$$$$$ 4.5")
#


    length = distinct_features_rdd.count()
    #--[(<hash>,[cnt1, cnt2, ...]]), ...]-------------------------------------------------------
    full_test_feature_count_rdd = full_features_index_count_rdd.map(lambda x: (x[0],Vectors.dense(list(build_full_feature_list(x[1],length)))))
    
    test_rdd = full_test_feature_count_rdd.map(lambda x: len(list(x[1])))
    print(test_rdd.take(1))
    print("$$$$$$$$$$$5")
    
    return full_test_feature_count_rdd


def RF_structure(all_features_count):
    '''
        --input-------------------------------------
        all_features_count : [((<hash>,<ngram feature>),cnt), ...]
        
        --output------------------------------------
        full_feature_count_rdd : [((<hash1>,<label1>),[cnt1,cnt2,...]), ...]
        '''
    #--[(<ngram feature>,index), ...]------------------------------------------------
    distinct_features_rdd = all_features_count.map(lambda x: x[0][1]).distinct().zipWithIndex()
    length = distinct_features_rdd.count()
    print("numb of features = "+str(length))
    #--[(<ngram feature>,(<hash>,cnt)), ...]-----------------------------------------
    all_features_count_rdd = all_features_count.map(lambda x: (x[0][1],(x[0][0],x[1])))
    print(all_features_count_rdd.take(1))
    print("$$$$$$$$$$$1")
    #--[(<hash>,(index,cnt)), ...]---------------------------------------------------
    feature_id_count_rdd = distinct_features_rdd.join(all_features_count_rdd).map(lambda x: (x[1][1][0],(x[1][0],x[1][1][1])))
    print(feature_id_count_rdd.take(1))
    print("$$$$$$$$$$$2")
    #--[(<hash>,[(index,cnt), ...]), ...]--------------------------------------------
    feature_id_count_rdd = feature_id_count_rdd.groupByKey().map(lambda x: (x[0],np.asarray(list(x[1]),dtype=int)))
#    a = feature_id_count_rdd.take(1)[0][1]
#    full_feature_narray = np.zeros(length,)
#    full_feature_narray[a[:,0]] = a[:,1]
#    print(full_feature_narray)
    print("$$$$$$$$$$$3")
    #--[(<hash>,[cnt1,cnt2,...]), ...]-----------------------------------------------
    full_feature_count_rdd = feature_id_count_rdd.map(lambda x: (x[0], Vectors.dense(list(build_full_feature_list(x[1],length)))))
#    print(full_feature_count_rdd.take(1))
    test_rdd = full_feature_count_rdd.map(lambda x: len(list(x[1])))
    print(test_rdd.take(1))
    print("$$$$$$$$$$$4")
#    return 0
    return full_feature_count_rdd, distinct_features_rdd

def create_indexed_df(full_train_feature_rdd):
    '''
        input : [(<hash1>,label1,[cnt1,cnt2,...]), ...]
        '''
    df = spark.createDataFrame(full_train_feature_rdd).toDF("name","label", "features")
    
    stringIndexer = StringIndexer(inputCol="name", outputCol="indexed")
    si_model = stringIndexer.fit(df)
    indexed_df = si_model.transform(df)
    indexed_df.show()
    return indexed_df

def RF(indexed_df):
    RF_model = RandomForestClassifier(numTrees=10, maxDepth=7, labelCol="label")
    td_new = change_column_datatype(indexed_df,"label",DoubleType)
    model = RF_model.fit(td_new)
    return model

def change_column_datatype(td,col_name,datatype):
    td_new = td.withColumn(col_name, td[col_name].cast(datatype()))
    return td_new

if __name__ == "__main__":

    sc = SparkContext()
    spark = SparkSession.builder.master("yarn").appName("Word Count").config("spark.some.config.option", "some-value").getOrCreate()

    data_asm_folder_path = "gs://uga-dsp/project2/data/asm/"
    data_bytes_folder_path = "gs://uga-dsp/project2/data/bytes/"
    
    training_file_names = "gs://uga-dsp/project2/files/X_small_train.txt"
    training_label = "gs://uga-dsp/project2/files/y_small_train.txt"
    test_file_names = "gs://uga-dsp/project2/files/X_small_test.txt"
    test_label = "gs://uga-dsp/project2/files/y_small_test.txt"
    
    #---Read in the data names and labels------------------------------------------
    train_filenames_rdd = sc.textFile(training_file_names)
    train_filenames_list = train_filenames_rdd.collect()
    train_labels_rdd = sc.textFile(training_label)
    
    test_filenames_rdd =sc.textFile(test_file_names)
    test_filenames_list = test_filenames_rdd.collect()
    test_labels_rdd = sc.textFile(test_label)
    
    #---Read in actual bytes/asm files---------------------------------------------
    #---format: [(<hash1>,<content1>),(<hash2>,<content2>), ...] ------------------
    train_asm_file_rdd = preprocess(data_asm_folder_path, train_filenames_list,".asm")
    train_byte_file_rdd = preprocess(data_bytes_folder_path, train_filenames_list,".bytes")
    
    test_asm_file_rdd = preprocess(data_asm_folder_path, test_filenames_list,".asm")
    test_byte_file_rdd = preprocess(data_bytes_folder_path, test_filenames_list,".bytes")

    sc.setCheckpointDir('checkpoint/')
    
    #---Create a label+filename pair-----------------------------------------------
    #---output: [(<hash1>,<label1>), (<hash2>,<label2>), ...]
    filename_label_pair_rdd = get_filename_label_pair(train_filenames_rdd, train_labels_rdd)
    
    print(filename_label_pair_rdd.take(10))
    print("*******************00")
    
    #---Extract the feaures--------------------------------------------------------
    #---output: [(<hash1>,<feature1>), (<hash1>,<feature2>), ..., (<hashN>,<featureK>)]----
    train_bytes_rdd = extract_features(train_byte_file_rdd, 'bytes')
    freq_train_bytes_rdd = get_frequent_features(train_bytes_rdd)
    
#    train_segment_rdd = extract_features(train_asm_file_rdd, 'segment')

    train_opcode_rdd = extract_features(train_asm_file_rdd, 'opcode')
    freq_train_opcode_rdd = get_frequent_features(train_opcode_rdd)

    test_bytes_rdd = extract_features(test_byte_file_rdd, 'bytes')
    freq_test_bytes_rdd = get_frequent_features(test_bytes_rdd)
    
#    test_segment_rdd = extract_features(test_asm_file_rdd, 'segment')

    test_opcode_rdd = extract_features(test_asm_file_rdd, 'opcode')
    freq_test_opcode_rdd = get_frequent_features(test_opcode_rdd)

    print(freq_train_bytes_rdd.take(10))
    print("*******************01")
    
    #---Find segment frequency-----------------------------------------------------
    #---output: [((<hash>,<feature>),cnt), ...]------------------------------------
#    freq_train_segment_rdd = train_segment_rdd.map(lambda x: ((x),1)).reduceByKey(add).filter(lambda x: x[1]>100)
#    freq_test_segment_rdd = test_segment_rdd.map(lambda x: ((x),1)).reduceByKey(add).filter(lambda x: x[1]>100)

#    print(freq_train_segment_rdd.take(10))
#    print("*******************")

    #---Find N gram of the features------------------------------------------------
    #---output: [((<hash>,<ngram feature>),cnt), ...]------------------------------
    train_Ngram_bytes_rdd = Ngram(freq_train_bytes_rdd,1,3)
    train_Ngram_opcode_rdd = Ngram(freq_train_opcode_rdd,4,5)

    test_Ngram_bytes_rdd = Ngram(freq_test_bytes_rdd,1,3)
    test_Ngram_opcode_rdd = Ngram(freq_test_opcode_rdd,4,5)

    print(train_Ngram_opcode_rdd.take(10))
    print("*******************02")
    
    all_train_features_count = train_Ngram_bytes_rdd.union(train_Ngram_opcode_rdd)
#.sortBy(lambda x:x[1],ascending=False).zipWithIndex()
#    all_train_features_count = all_train_features_count.filter(lambda x: x[1]<7000).map(lambda x: x[0])

    all_test_features_count = test_Ngram_bytes_rdd.union(test_Ngram_opcode_rdd)
#.sortBy(lambda x:x[1],ascending=False).zipWithIndex()
#    all_test_features_count = all_test_features_count.filter(lambda x: x[1]<7000).map(lambda x: x[0])
#    all_train_features_count = train_Ngram_bytes_rdd
#    all_test_features_count = test_Ngram_bytes_rdd
    print(all_train_features_count.take(10))
    print("*******************03")

    #---Link label in------------------------------------------------------------------------
    #---output: [((<hash>,<label>),(<ngram feature>,cnt)), ...]------------------------------
#    all_train_features_count = all_train_features_count.map(lambda x: (x[0][0],(x[0][1],x[1])))
#    all_train_features_count = filename_label_pair_rdd.join(all_train_features_count).map(lambda x: ((x[0],x[1][0]),(x[1][1])))

    #---Pre Random Forest(Prepare for the data structure)----------------------------
    #---[(<hash1>,[cnt1,cnt2,...]), ...]---------------------------------------------
    full_train_feature_rdd, distinct_features_rdd = RF_structure(all_train_features_count)
    full_test_feature_rdd = test_RF_structure(all_test_features_count,distinct_features_rdd)
    print(full_test_feature_rdd.take(1))
    print("*******************04")
    
    #---Link label in----------------------------------------------------------------
    #---output: [(<hash1>,label1,[cnt1,cnt2,...]), ...]------------------------------
    full_train_feature_rdd = filename_label_pair_rdd.join(full_train_feature_rdd).map(lambda x: (x[0],x[1][0],x[1][1]))
    print("*******************05")
    
    feature_label_full_df = create_indexed_df(full_train_feature_rdd)
    
    training_model = RF(feature_label_full_df)
    print("finished RF training")
    
    #---testing---------------------------------------------------------------------
    test_feature_df = spark.createDataFrame(full_test_feature_rdd).toDF("name","features")
    stringIndexer = StringIndexer(inputCol="name", outputCol="indexed")
    test_model = stringIndexer.fit(test_feature_df)
    test_feature_indexed_df = test_model.transform(test_feature_df)
    

    #---Prediction------------------------------------------------------------------
    print("*************** Start transforming*******************")
    result = training_model.transform(test_feature_indexed_df)
    result = result.withColumn("prediction", result["prediction"].cast("int"))
    result.show()
    result = result.select("prediction","name")
    rdd = result.rdd.map(tuple).map(lambda x: (x[1],x[0]))
    test_file_names = test_filenames_rdd.zipWithIndex()
    print("*************** 345*******************")
#    print(test_file_names)
    predict = rdd.join(test_file_names).sortBy(lambda x: x[1][1]).map(lambda x:x[1][0]).collect()
    print(predict)
#.sortBy(lambda x: x[1]).map(lambda x: x[0])
#    predict = rdd.collect()
#    print(predict)
    test_rdd_label = test_labels_rdd.collect()
    score = 0
    all_count = rdd.count()
    print("predict numb " + str(len(predict)) + " rdd all_count " + str(all_count))
    for i in range(len(predict)):
        predict[i] = str(predict[i])
        print(predict[i])
        print(test_rdd_label[i])
        if predict[i] == test_rdd_label[i]:
            score +=1
    print("accuracy = " + str(score*100/all_count))
#    result.select("prediction","indexed").write.csv('gs://p2_malware/output_small/')






















