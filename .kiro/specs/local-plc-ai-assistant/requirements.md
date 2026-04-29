# Requirements Document

## Introduction

The Local PLC AI Assistant is a locally-running system that assists users in writing, validating, and simulating PLC code for Mitsubishi PLCs. The system uses a local LLM via Ollama to provide AI-powered code generation, leverages manufacturer documentation and existing code samples as context, and includes digital twin simulation capabilities to verify code correctness before deployment.

## Glossary

- **PLC_Assistant**: The AI-powered system that helps users write and validate PLC code
- **Ollama_Service**: The local LLM service that provides AI capabilities
- **Context_Manager**: Component that manages reference documentation and sample code
- **Code_Generator**: Component that generates Ladder Logic and Structured Text code
- **Code_Validator**: Component that validates PLC code syntax and semantics
- **Digital_Twin**: Virtual simulation environment that mimics physical PLC behavior
- **Ladder_Logic**: Graphical programming language for PLCs using relay logic symbols
- **Structured_Text**: High-level textual programming language for PLCs
- **Mitsubishi_Manual**: The ST Programming guide book PDF provided by the manufacturer
- **Sample_Programs**: Existing PLC programs used as reference examples

## Requirements

### Requirement 1: Local LLM Integration

**User Story:** As a PLC programmer, I want to use a local LLM for code assistance, so that I can work without internet connectivity or cloud dependencies.

#### Acceptance Criteria

1. THE PLC_Assistant SHALL integrate with Ollama_Service running on the local machine
2. THE PLC_Assistant SHALL support Qwen2.5-Coder and DeepSeek-Coder models
3. WHEN Ollama_Service is unavailable, THE PLC_Assistant SHALL display a connection error message
4. THE PLC_Assistant SHALL send code generation requests to Ollama_Service with appropriate context


### Requirement 2: Reference Documentation Management

**User Story:** As a PLC programmer, I want the system to use Mitsubishi's ST programming manual as context, so that generated code follows manufacturer specifications.

#### Acceptance Criteria

1. THE Context_Manager SHALL load and parse the Mitsubishi_Manual PDF file
2. THE Context_Manager SHALL extract relevant sections from Mitsubishi_Manual based on user queries
3. THE Context_Manager SHALL provide extracted documentation to Ollama_Service as context
4. WHEN Mitsubishi_Manual is not found, THE Context_Manager SHALL display a warning message

### Requirement 3: Sample Program Integration

**User Story:** As a PLC programmer, I want the system to learn from my existing PLC programs, so that generated code matches my coding style and patterns.

#### Acceptance Criteria

1. THE Context_Manager SHALL load Sample_Programs from the references directory
2. THE Context_Manager SHALL parse PLC program files in .pro format
3. THE Context_Manager SHALL extract code patterns and structures from Sample_Programs
4. WHEN generating code, THE Code_Generator SHALL reference Sample_Programs as examples

### Requirement 4: Structured Text Code Generation

**User Story:** As a PLC programmer, I want to generate Structured Text code with AI assistance, so that I can write PLC programs more efficiently.

#### Acceptance Criteria

1. WHEN a user provides a code description, THE Code_Generator SHALL generate valid Structured_Text code
2. THE Code_Generator SHALL follow Mitsubishi ST language syntax rules
3. THE Code_Generator SHALL include code comments explaining the logic
4. THE Code_Generator SHALL reference Mitsubishi_Manual for language-specific constructs

### Requirement 5: Ladder Logic Code Generation

**User Story:** As a PLC programmer, I want to generate Ladder Logic code with AI assistance, so that I can create visual PLC programs efficiently.

#### Acceptance Criteria

1. WHEN a user provides a logic description, THE Code_Generator SHALL generate valid Ladder_Logic code
2. THE Code_Generator SHALL output Ladder_Logic in a format compatible with Mitsubishi PLCs
3. THE Code_Generator SHALL organize ladder rungs logically with appropriate labels
4. THE Code_Generator SHALL include rung comments explaining the logic

### Requirement 6: Code Syntax Validation

**User Story:** As a PLC programmer, I want the system to validate my code syntax, so that I can catch errors before uploading to the PLC.

#### Acceptance Criteria

1. WHEN code is generated or modified, THE Code_Validator SHALL check syntax against Mitsubishi language specifications
2. IF syntax errors are detected, THEN THE Code_Validator SHALL display error messages with line numbers
3. THE Code_Validator SHALL validate variable declarations and data types
4. THE Code_Validator SHALL check for undefined variables and functions

### Requirement 7: Code Semantic Validation

**User Story:** As a PLC programmer, I want the system to check code logic, so that I can identify potential runtime issues before deployment.

#### Acceptance Criteria

1. THE Code_Validator SHALL detect unreachable code segments
2. THE Code_Validator SHALL identify potential infinite loops
3. THE Code_Validator SHALL warn about uninitialized variables
4. THE Code_Validator SHALL check for timing conflicts in ladder logic

### Requirement 8: Digital Twin Simulation Environment

**User Story:** As a PLC programmer, I want to simulate PLC code behavior in a virtual environment, so that I can verify correctness before deploying to physical machines.

#### Acceptance Criteria

1. THE Digital_Twin SHALL execute PLC code in a simulated runtime environment
2. THE Digital_Twin SHALL maintain virtual I/O states during simulation
3. THE Digital_Twin SHALL update simulation state based on code execution
4. THE Digital_Twin SHALL log all state changes during simulation

### Requirement 9: 3D Visualization Integration

**User Story:** As a PLC programmer, I want to visualize equipment behavior during simulation, so that I can see how my code affects physical systems.

#### Acceptance Criteria

1. WHERE STL_Model files are provided, THE Digital_Twin SHALL load and display 3D models
2. WHILE simulation is running, THE Digital_Twin SHALL animate 3D models based on I/O states
3. THE Digital_Twin SHALL map PLC outputs to corresponding 3D model movements
4. THE Digital_Twin SHALL support common 3D file formats including STL

### Requirement 10: Simulation Execution Control

**User Story:** As a PLC programmer, I want to control simulation execution, so that I can step through code and observe behavior.

#### Acceptance Criteria

1. THE Digital_Twin SHALL support start, stop, pause, and resume simulation commands
2. THE Digital_Twin SHALL support step-by-step execution mode
3. THE Digital_Twin SHALL allow users to set breakpoints in code
4. WHEN a breakpoint is reached, THE Digital_Twin SHALL pause execution and display current state

### Requirement 11: Simulation Input Control

**User Story:** As a PLC programmer, I want to control virtual inputs during simulation, so that I can test different scenarios.

#### Acceptance Criteria

1. WHILE simulation is running, THE Digital_Twin SHALL allow users to toggle virtual input states
2. THE Digital_Twin SHALL display current values of all inputs and outputs
3. THE Digital_Twin SHALL support setting analog input values within valid ranges
4. THE Digital_Twin SHALL validate input values before applying them

### Requirement 12: Code Correctness Verification

**User Story:** As a PLC programmer, I want to verify code correctness through simulation, so that I can confidently deploy to production machines.

#### Acceptance Criteria

1. THE Digital_Twin SHALL execute test scenarios against PLC code
2. THE Digital_Twin SHALL compare actual outputs against expected outputs
3. IF outputs do not match expectations, THEN THE Digital_Twin SHALL report verification failures
4. THE Digital_Twin SHALL generate a verification report summarizing test results

### Requirement 13: User Interface

**User Story:** As a PLC programmer, I want an intuitive interface to interact with the system, so that I can efficiently write and test code.

#### Acceptance Criteria

1. THE PLC_Assistant SHALL provide a code editor with syntax highlighting for Structured_Text and Ladder_Logic
2. THE PLC_Assistant SHALL display validation errors inline in the code editor
3. THE PLC_Assistant SHALL provide separate panels for code editing, simulation control, and 3D visualization
4. THE PLC_Assistant SHALL allow users to save and load PLC projects

### Requirement 14: Local Data Storage

**User Story:** As a PLC programmer, I want all data stored locally, so that my code and projects remain private and secure.

#### Acceptance Criteria

1. THE PLC_Assistant SHALL store all user projects on the local filesystem
2. THE PLC_Assistant SHALL store reference documentation locally
3. THE PLC_Assistant SHALL NOT transmit any code or data to external servers
4. THE PLC_Assistant SHALL store simulation configurations locally

### Requirement 15: Code Export

**User Story:** As a PLC programmer, I want to export validated code, so that I can upload it to my physical PLC.

#### Acceptance Criteria

1. THE PLC_Assistant SHALL export Structured_Text code in formats compatible with Mitsubishi programming software
2. THE PLC_Assistant SHALL export Ladder_Logic in formats compatible with Mitsubishi programming software
3. WHEN exporting code, THE PLC_Assistant SHALL include all variable declarations and program organization units
4. THE PLC_Assistant SHALL validate code before allowing export
