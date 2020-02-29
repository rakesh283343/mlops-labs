# Copyright 2019 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#            http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Covertype training pipeline DSL."""

import os
from typing import Optional, Dict, List, Text

from kfp import gcp
from tfx.components.base import executor_spec
from tfx.components import Evaluator
from tfx.components import CsvExampleGen
from tfx.components import ExampleValidator
from tfx.components import ImporterNode
from tfx.components import ModelValidator
from tfx.components import Pusher
from tfx.components import SchemaGen
from tfx.components import StatisticsGen
from tfx.components import Trainer
from tfx.components import Transform
from tfx.extensions.google_cloud_ai_platform.pusher import executor as ai_platform_pusher_executor
from tfx.extensions.google_cloud_ai_platform.trainer import executor as ai_platform_trainer_executor
from tfx.orchestration import data_types
from tfx.orchestration import pipeline
from tfx.orchestration.kubeflow import kubeflow_dag_runner
from tfx.orchestration.kubeflow.proto import kubeflow_pb2
from tfx.proto import evaluator_pb2
from tfx.proto import trainer_pb2
from tfx.utils.dsl_utils import external_input
from tfx.types.standard_artifacts import Schema



def _create__pipeline(pipeline_name: Text, 
                      pipeline_root: Text, 
                      data_root_uri: data_types.RuntimeParameter,
                      module_file_uri: data_types.RuntimeParameter, 
                      schema_file_uri: data_types.RuntimeParameter,
                      train_steps: data_types.RuntimeParameter,
                      eval_steps: data_types.RuntimeParameter,
                      ai_platform_training_args: Dict[Text, Text],
                      ai_platform_serving_args: Dict[Text, Text],
                      beam_pipeline_args: List[Text],
                      enable_cache: Optional[bool] = True) -> pipeline.Pipeline:
  """Implements the online news pipeline with TFX."""

  examples = external_input(data_root_uri)

  # Brings data into the pipeline or otherwise joins/converts training data.
  generate_examples = CsvExampleGen(input=examples)

  
  # Computes statistics over data for visualization and example validation.
  generate_statistics = StatisticsGen(examples=generate_examples.outputs.examples)

  # Import a user-provided schema
  import_schema = ImporterNode(
      instance_name='import_user_schema',
      source_uri=schema_file_uri,
      artifact_type=Schema)
  
  # Generates schema based on statistics files.Even though, we use user-provided schema
  # we still want to generate the schema of the newest data for tracking and comparison
  infer_schema = SchemaGen(statistics=generate_statistics.outputs.statistics)

  # Performs anomaly detection based on statistics and data schema.
  validate_stats = ExampleValidator(
      statistics=generate_statistics.outputs.statistics, 
      schema=import_schema.outputs.result)

  # Performs transformations and feature engineering in training and serving.
  transform = Transform(
      examples=generate_examples.outputs.examples,
      schema=import_schema.outputs.result,
      module_file=module_file_uri)

  # Uses user-provided Python function that implements a model using
  # TensorFlow's Estimators API.
  train = Trainer(
      custom_executor_spec=executor_spec.ExecutorClassSpec(
          ai_platform_trainer_executor.Executor),
      module_file=module_file_uri,
      transformed_examples=transform.outputs.transformed_examples,
      schema=import_schema.outputs.result,
      transform_graph=transform.outputs.transform_graph,
      train_args={'num_steps': train_steps},
      eval_args={'num_steps': eval_steps},
      custom_config={'ai_platform_training_args': ai_platform_training_args})

  # Uses TFMA to compute a evaluation statistics over features of a model.
  analyze = Evaluator(
      examples=generate_examples.outputs.examples,
      model=train.outputs.model)

  # Performs quality validation of a candidate model (compared to a baseline).
  validate = ModelValidator(
      examples=generate_examples.outputs.examples, 
      model=train.outputs.model)

  # Checks whether the model passed the validation steps and pushes the model
  # to a file destination if check passed.
  deploy = Pusher(
      custom_executor_spec=executor_spec.ExecutorClassSpec(
          ai_platform_pusher_executor.Executor),
      model=train.outputs.model,
      model_blessing=validate.outputs.blessing,
      custom_config={'ai_platform_serving_args': ai_platform_serving_args})

  return pipeline.Pipeline(
      pipeline_name=pipeline_name,
      pipeline_root=pipeline_root,
      components=[
          generate_examples, generate_statistics, import_schema, infer_schema, validate_stats, transform,
          train, analyze, validate, deploy
      ],
      enable_cache=enable_cache,
      beam_pipeline_args=beam_pipeline_args
  )


if __name__ == '__main__':

  # Get evironment settings from environment variables
  pipeline_name = os.environ.get('PIPELINE_NAME')
  project_id = os.environ.get('PROJECT_ID')
  gcp_region = os.environ.get('GCP_REGION')
  pipeline_image = os.environ.get('TFX_IMAGE')
  data_root_uri = os.environ.get('DATA_ROOT_URI')
  artifact_store_uri = os.environ.get('ARTIFACT_STORE_URI')
  runtime_version = os.environ.get('RUNTIME_VERSION')
  python_version = os.environ.get('PYTHON_VERSION')

  # Set values for the compile time parameters
    
  ai_platform_training_args = {
      'project': project_id,
      'region': gcp_region,
      'masterConfig': {
          'imageUri': pipeline_image,
      }
  }

  ai_platform_serving_args = {
      'model_name': 'model_' + pipeline_name,
      'project_id': project_id,
      'runtimeVersion': runtime_version,
      'pythonVersion': python_version
  }

  beam_tmp_folder = '{}/beam/tmp'.format(artifact_store_uri)
  beam_pipeline_args = [
      '--runner=DataflowRunner',
      '--experiments=shuffle_mode=auto',
      '--project=' + project_id,
      '--temp_location=' + beam_tmp_folder,
      '--region=' + gcp_region,
  ]
  
  # Set default values for the pipeline runtime parameters
    
  module_file_uri = data_types.RuntimeParameter(
      name='module-file_uri',
      default='transform_train.py',
      ptype=Text,
  )

  schema_file_uri = data_types.RuntimeParameter(
      name='schema-file_uri',
      default='schema.pbtxt',
      ptype=Text,
  )
  
  data_root_uri = data_types.RuntimeParameter(
      name='data-root-uri',
      default=data_root_uri,
      ptype=Text
  )

  train_steps = data_types.RuntimeParameter(
      name='train-steps',
      default=500,
      ptype=int
  )
    
  eval_steps = data_types.RuntimeParameter(
      name='eval-steps',
      default=500,
      ptype=int
  )
  
  pipeline_root = '{}/{}'.format(artifact_store_uri, pipeline_name)
    
  
  # Set KubeflowDagRunner settings
  metadata_config = kubeflow_dag_runner.get_default_kubeflow_metadata_config()
  operator_funcs = kubeflow_dag_runner. get_default_pipeline_operator_funcs(use_gcp_sa=True)
    
  runner_config = kubeflow_dag_runner.KubeflowDagRunnerConfig(
      kubeflow_metadata_config=metadata_config,
      pipeline_operator_funcs=operator_funcs,
      tfx_image=pipeline_image)

  # Compile the pipeline
  kubeflow_dag_runner.KubeflowDagRunner(config=runner_config).run(
      _create__pipeline(
          pipeline_name=pipeline_name,
          pipeline_root=pipeline_root,
          data_root_uri=data_root_uri,
          module_file_uri=module_file_uri,
          schema_file_uri=schema_file_uri,
          train_steps=train_steps,
          eval_steps=eval_steps,
          ai_platform_training_args=ai_platform_training_args,
          ai_platform_serving_args=ai_platform_serving_args,
          beam_pipeline_args=beam_pipeline_args))