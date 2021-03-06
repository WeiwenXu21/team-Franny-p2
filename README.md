# team-Franny-p2

# Project 2: Malware Classification

This project is a problem of Malware classification given asm and bytes files of malware from one of 9 classes. Each class is labeled as number between 1 to 9. 

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See deployment for notes on how to deploy the project on a live system.

### Prerequisites

- [Python 3.6](https://www.python.org/downloads/release/python-360/)
- [Apache Spark 2.2.1](http://spark.apache.org/)
- [Pyspark 2.2.1](https://pypi.python.org/pypi/pyspark/2.2.1) - Python API for Apache Spark
- [Google Cloud Platform](https://cloud.google.com) - File is extremely large so cloud computing is essential
- [Anaconda](https://www.anaconda.com/)

### Environment Setup
### Anaconda

Anaconda is a complete Python distribution embarking automatically the most common packages, and allowing an easy installation of new packages.

Download and install Anaconda (https://www.continuum.io/downloads).

### Spark

Download the latest, pre-built for Hadoop 2.6, version of Spark.
* Go to http://spark.apache.org/downloads.html
* Choose a release
* Choose a package type: Pre-built for Hadoop 2.6 and later
* Choose a download type: Direct Download
* Click on the link in Step 4
* Once downloaded, unzip the file and place it in a directory of your choice

Go to [WIKI](https://github.com/dsp-uga/team-andromeda-p1/wiki) tab for more details of running IDE for Pyspark. ([IDE Setting for Pyspark](https://github.com/dsp-uga/team-andromeda-p1/wiki/IDE-Setting-for-Pyspark))

## Running the tests

You can run `p2-GCP-RF.py` via regular **python** or run the script via **spark-submit**. You should specify the path to your spark-submit.

```
$ python your/path/to/team-Franny-p2/src/p2-GCP-RF.py	
```
```
$ usr/bin/spark-submit your/path/to/team-Franny-p2/src/p2-GCP-RF.py
```

If you want to run it on GCP through your local terminal, you can submit a job using dataproc.

```
gcloud dataproc jobs submit pyspark path/to/team-Franny-p2/src/p2-GCP-RF.py --cluster=your-cluster-name -- [asm-file-folder-path] [bytes-file-folder-path] [training-file-path] [training-label-path] [testing-file-path] [GCP-output-path] -t [testing-label-path-if-needed]

```

The output prediction will be saved to your GCP Bucket with the path you provided.

### Packages Used

#### Ngram from pyspark.ml.feature

```
from pyspark.ml.feature import NGram
```

NGram from pyspark.ml package is used to extract the Ngram features given tokenized bytes or opcodes. It requires to convert rdd data to dataframe for the process with a column containing all the tokenized features in on list. Order of these features is required to be the same as they are in the file. For more information on Ngram, please go to [WIKI](https://github.com/dsp-uga/team-Franny-p2/wiki/N-grams).

#### RandomForestClassifier from pyspark.ml.classification

```
from pyspark.ml.classification import RandomForestClassifier
```

RandomForestClassifier is used for modeling and making predictions for this problem. The concept of Random Forest classification is explained in [WIKI](https://github.com/dsp-uga/team-Franny-p2/wiki/RANDOM-FOREST-ALGORITHM).

### Overview

This projects mainly uses [Random Forest Classifier](https://github.com/dsp-uga/team-Franny-p2/wiki/RANDOM-FOREST-ALGORITHM) with several preprcessing methods. Here's the brief flow to explain the code:

1. Bytes tokenizing by regular expression `r'\s([A-F0-9]{2})\s` that matches two hexadecimal pairs with space in both end.
2. Ngram Bytes feature construction. Here in the final code, we used 1 and 2 gram bytes.
3. Get the most frequent features to prevent overfitting and memory issue. We kept all 256 1-gram bytes and the most frequent 1000 2-gram bytes in the end.
4. Construct the data structure for RandomForestClassifier. The final data structure before converting into data frame is `[(<hash1>,label1,[cnt1,cnt2,...]), ...]`
5. Random Forest Classification.

### Experiment on Features:

During our implementation, we tried to use different features and different combinations of several features for training the model. Here are the features that we extracted. Results of different combinations are shown in [Result section](https://github.com/dsp-uga/team-Franny-p2/blob/master/README.md#result). 

* **Segment** First token of each line in asm files such as `HEADER, text, data, rsrc, CODE` etc.

* **Byte** Hexadecimal pairs in bytes files.

* **Opcode** Opcodes in asm files such as `cmp, jz, mov, sub` etc.

### Experiment on Dimension Reduction:

Since the files are large, features extracted from them are extremely large. Therefore, feature dimension reduction is essential to prevent from overfitting and also reduce the processing time.

* **IDF** 

We tried setting IDF threshold to filter out some "less meaningful" opcodes. Since opcodes are for specifying what to do in assembly language, it seems reasonable to check whether this opcode is special to this file meaning or it's a opcode that appears commonly across all files (similar to stopwords).

* **Or simply filter out less frequency features** 

#### Feature Selection

## Result

We tried several feature extractions to see which one performs best (we only have one result on large set): 

|Features                               |Accuracy on Small|Accuracy on Large|
|---------------------------------------|-----------------|-----------------|
|segment count                          |73.21%           |94.85%           |
|1-gram Bytes                           |89.94%           |N/A              |
|1-gram & 2-gram Bytes                  |90.53%           |N/A              |
|segment count & 1-gram bytes           |93.49%           |N/A              |
|segment count & 1-gram & 2-gram Bytes  |92.90%           |N/A              |
|1-gram & 2-gram opcodes                |95.85%           |N/A              |
|segment count & 1-gram & 2-gram opcodes|95.86%           |N/A              |
|segment count & 4-gram opcodes         |94.08%           |N/A              |

## Other Experiment We Tried:

* **Word2vec from org.apache.spark.ml.feature.Word2Vec**
We tried Word2vec package to map words, in our case, segment counts and 1 to 4-gram opcodes into fixed-size vector for each document. This requires total different a different data structure — dataframe instead of rdds. We did not successfully implement this on large dataset because the method was not very scalable. Implementing the Word2vec resulted in OutOfMemoryError in GCP.

* **Cross Validation from pyspark.ml.tuning.CrossValidator**
We used 4-fold cross validator to tune the parameters of different models. The method lead to selecting a more stable performance and less overfitting problem.

* **MLPC from pyspark.ml.classification.MultilayerPerceptronClassifier**
We used the MLPC package on features selected from Word2vec. Because of our implementation of Word2vec was not scalable, we did not use this model in the end. We did not have enough time to further experiment on this method

* **Naive Bayes from pyspark.ml.classification.NaiveBayes**
We used the Naive Bayes package on features selected from idf method. Due to vaious feature size in different experiment, the parametor which was tuned in small dataset did not fit well on the large dataset.

## Contributing

Please read [CONTRIBUTING.md](https://github.com/dsp-uga/team-Franny-p2/blob/master/CONTRIBUTORS.md) for details.

## Authors

* **Aishwarya Jagtap** - 
* **Ailing Wang** - 
* **Weiwen Xu** - [WeiwenXu21](https://github.com/WeiwenXu21)

See also the list of [contributors](https://github.com/dsp-uga/team-Franny-p2/blob/master/CONTRIBUTORS.md) who participated in this project.

## License

This project is licensed under the MIT License - see the [LICENSE.md](https://github.com/dsp-uga/team-Franny-p2/blob/master/LICENSE) file for details
